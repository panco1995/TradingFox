package api

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

// Backfilling a year of 1m bars takes minutes, so it cannot run inside a request.
// A job is started, the handler returns immediately, and the UI polls for its
// state. Only one backfill per symbol may run: the collector writes the same
// Parquet files, and two writers would fight over the file lock for no gain.

type backfillJob struct {
	Symbol    string          `json:"symbol"`
	State     string          `json:"state"` // pending | running | done | error
	StartedAt time.Time       `json:"started_at"`
	EndedAt   *time.Time      `json:"ended_at"`
	Result    json.RawMessage `json:"result"`
	Error     string          `json:"error,omitempty"`
}

type backfillRegistry struct {
	mu   sync.Mutex
	jobs map[string]*backfillJob
}

func newBackfillRegistry() *backfillRegistry {
	return &backfillRegistry{jobs: make(map[string]*backfillJob)}
}

func (r *backfillRegistry) start(symbol string) (*backfillJob, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if existing, ok := r.jobs[symbol]; ok {
		if existing.State == "pending" || existing.State == "running" {
			return existing, false
		}
	}
	job := &backfillJob{Symbol: symbol, State: "pending", StartedAt: time.Now().UTC()}
	r.jobs[symbol] = job
	return job, true
}

func (r *backfillRegistry) finish(symbol string, result json.RawMessage, err error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	job, ok := r.jobs[symbol]
	if !ok {
		return
	}
	now := time.Now().UTC()
	job.EndedAt = &now
	if err != nil {
		job.State = "error"
		job.Error = err.Error()
		return
	}
	job.State = "done"
	job.Result = result
}

func (r *backfillRegistry) markRunning(symbol string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	if job, ok := r.jobs[symbol]; ok {
		job.State = "running"
	}
}

func (r *backfillRegistry) get(symbol string) (backfillJob, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()
	job, ok := r.jobs[symbol]
	if !ok {
		return backfillJob{}, false
	}
	return *job, true
}

func (r *backfillRegistry) snapshot() []backfillJob {
	r.mu.Lock()
	defer r.mu.Unlock()
	out := make([]backfillJob, 0, len(r.jobs))
	for _, job := range r.jobs {
		out = append(out, *job)
	}
	return out
}

// handleBackfillPlan reports what is missing without downloading anything, so
// the UI can tell the user "already complete" before they wait for a job.
func (s *Server) handleBackfillPlan(c *gin.Context) {
	symbol := strings.ToUpper(strings.TrimSpace(c.Query("symbol")))
	days, err := parseBoundedInt(c.Query("days"), 365, 1, 3650)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "天数需要在 1 到 3650 之间"})
		return
	}
	if symbol == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请指定交易对"})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 120*time.Second)
	defer cancel()

	payload, err := s.quant.BackfillPlan(ctx, symbol, days, "1m")
	if err != nil {
		s.fail(c, "检查数据完整性失败", err)
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

// handleStartBackfill kicks off the download and returns at once.
func (s *Server) handleStartBackfill(c *gin.Context) {
	var req struct {
		Symbol string `json:"symbol"`
		Days   int    `json:"days"`
		Force  bool   `json:"force"`
	}
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	symbol := strings.ToUpper(strings.TrimSpace(req.Symbol))
	if symbol == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请指定交易对"})
		return
	}
	if req.Days <= 0 {
		req.Days = 365
	}
	if req.Days < 1 || req.Days > 3650 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "天数需要在 1 到 3650 之间"})
		return
	}

	job, started := s.backfills.start(symbol)
	if !started {
		c.JSON(http.StatusConflict, gin.H{
			"error": symbol + " 正在回填中，请等待完成",
			"job":   job,
		})
		return
	}

	go s.runBackfill(symbol, req.Days, req.Force)
	c.JSON(http.StatusAccepted, job)
}

func (s *Server) runBackfill(symbol string, days int, force bool) {
	// The job outlives the request that started it, so it must not inherit the
	// request context: that gets cancelled as soon as the handler returns.
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Minute)
	defer cancel()

	s.backfills.markRunning(symbol)
	payload, err := s.quant.Backfill(ctx, symbol, days, "1m", force)
	s.backfills.finish(symbol, payload, err)
	if err != nil {
		s.log.Error("backfill failed", "symbol", symbol, "err", err)
		return
	}
	s.log.Info("backfill finished", "symbol", symbol, "days", days)
}

func (s *Server) handleBackfillStatus(c *gin.Context) {
	symbol := strings.ToUpper(strings.TrimSpace(c.Param("symbol")))
	if symbol == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请指定交易对"})
		return
	}
	job, ok := s.backfills.get(symbol)
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "没有该交易对的回填任务"})
		return
	}
	c.JSON(http.StatusOK, job)
}

func (s *Server) handleListBackfills(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"jobs": s.backfills.snapshot()})
}
