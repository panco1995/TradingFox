package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/store"
)

type runSummaryDTO struct {
	ID          int64           `json:"id"`
	Strategy    string          `json:"strategy"`
	Symbols     json.RawMessage `json:"symbols"`
	ReportDir   string          `json:"report_dir"`
	TotalReturn *float64        `json:"total_return"`
	FinalEquity *float64        `json:"final_equity"`
	CreatedAt   time.Time       `json:"created_at"`
}

func (s *Server) handleListRuns(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	if s.cfg.Runs == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "回测历史未配置"})
		return
	}
	limit := 20
	if raw := c.Query("limit"); raw != "" {
		if value, err := strconv.Atoi(raw); err == nil {
			limit = value
		}
	}
	if limit < 1 {
		limit = 1
	}
	if limit > 100 {
		limit = 100
	}

	runs, err := s.cfg.Runs.ListRuns(c.Request.Context(), user.ID, limit)
	if err != nil {
		s.log.Error("list runs failed", "user_id", user.ID, "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "读取回测历史失败"})
		return
	}
	out := make([]runSummaryDTO, 0, len(runs))
	for _, run := range runs {
		symbols := json.RawMessage(run.Symbols)
		if !json.Valid(symbols) {
			symbols = json.RawMessage("[]")
		}
		out = append(out, runSummaryDTO{
			ID:          run.ID,
			Strategy:    run.Strategy,
			Symbols:     symbols,
			ReportDir:   run.ReportDir,
			TotalReturn: run.TotalReturn,
			FinalEquity: run.FinalEquity,
			CreatedAt:   run.CreatedAt,
		})
	}
	c.JSON(http.StatusOK, out)
}

func (s *Server) handleGetRun(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	if s.cfg.Runs == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "回测历史未配置"})
		return
	}
	id, err := strconv.ParseInt(c.Param("id"), 10, 64)
	if err != nil || id <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "无效的回测 ID"})
		return
	}
	run, err := s.cfg.Runs.GetRun(c.Request.Context(), user.ID, id)
	if errors.Is(err, store.ErrNotFound) {
		c.JSON(http.StatusNotFound, gin.H{"error": "回测不存在"})
		return
	}
	if err != nil {
		s.log.Error("get run failed", "user_id", user.ID, "run_id", id, "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "读取回测失败"})
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", []byte(run.ResultJSON))
}
