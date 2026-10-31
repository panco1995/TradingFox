// Package httpapi exposes the admin API and the embedded web UI.
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"time"

	"github.com/tm00013/trading/backend/internal/quantcli"
	"github.com/tm00013/trading/backend/web"
)

const (
	maxBodyBytes = 256 << 10
	version      = "0.2.0"
)

// Quant is the subset of the Python CLI the HTTP layer needs. Keeping it an
// interface lets handler tests run without spawning Python.
type Quant interface {
	Strategies(ctx context.Context) (json.RawMessage, error)
	Backtest(ctx context.Context, req quantcli.BacktestRequest) (json.RawMessage, error)
}

type Server struct {
	quant Quant
	log   *slog.Logger
	sem   chan struct{} // one backtest at a time
}

func New(quant Quant, logger *slog.Logger) *Server {
	return &Server{
		quant: quant,
		log:   logger,
		sem:   make(chan struct{}, 1),
	}
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/health", s.handleHealth)
	mux.HandleFunc("GET /api/strategies", s.handleStrategies)
	mux.HandleFunc("POST /api/backtests", s.handleBacktest)
	mux.Handle("GET /", s.staticHandler())
	return withLogging(s.log, withHeaders(mux))
}

func (s *Server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":  "ok",
		"version": version,
		"time":    time.Now().UTC().Format(time.RFC3339),
	})
}

func (s *Server) handleStrategies(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()

	payload, err := s.quant.Strategies(ctx)
	if err != nil {
		s.fail(w, "读取策略列表失败", err)
		return
	}
	writeRaw(w, http.StatusOK, payload)
}

func (s *Server) handleBacktest(w http.ResponseWriter, r *http.Request) {
	select {
	case s.sem <- struct{}{}:
		defer func() { <-s.sem }()
	default:
		writeJSON(w, http.StatusConflict, map[string]string{
			"error": "已有回测在运行，请等待完成或刷新报告",
		})
		return
	}

	var req quantcli.BacktestRequest
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, maxBodyBytes))
	decoder.UseNumber()
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "请求体不合法: " + err.Error()})
		return
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "请求体只能包含一个 JSON 对象"})
		return
	}

	started := time.Now()
	payload, err := s.quant.Backtest(r.Context(), req)
	if err != nil {
		s.fail(w, "回测失败", err)
		return
	}
	s.log.Info("backtest finished",
		"strategy", req.Strategy,
		"symbols", req.Symbols,
		"duration_ms", time.Since(started).Milliseconds(),
	)
	writeRaw(w, http.StatusOK, payload)
}

func (s *Server) staticHandler() http.Handler {
	files := http.FileServer(http.FS(web.FS))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache")
		files.ServeHTTP(w, r)
	})
}

func (s *Server) fail(w http.ResponseWriter, prefix string, err error) {
	var cliErr *quantcli.Error
	if errors.As(err, &cliErr) {
		status := http.StatusBadGateway
		if cliErr.InvalidInput() {
			status = http.StatusBadRequest
		}
		if cliErr.ExitCode == -1 {
			status = http.StatusGatewayTimeout
		}
		s.log.Warn("quant cli failed", "error", cliErr.Message, "exit", cliErr.ExitCode)
		writeJSON(w, status, map[string]string{"error": cliErr.Message})
		return
	}
	s.log.Error("internal error", "err", err)
	writeJSON(w, http.StatusInternalServerError, map[string]string{"error": prefix + ": " + err.Error()})
}

func writeRaw(w http.ResponseWriter, status int, payload []byte) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if _, err := w.Write(payload); err != nil {
		slog.Error("write response", "err", err)
	}
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		slog.Error("encode response", "err", err)
	}
}

func withHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Referrer-Policy", "no-referrer")
		w.Header().Set("Content-Security-Policy",
			"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'")
		next.ServeHTTP(w, r)
	})
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

func withLogging(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		logger.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rec.status,
			"duration_ms", time.Since(start).Milliseconds(),
		)
	})
}
