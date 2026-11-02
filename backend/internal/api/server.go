// Package api exposes the trading platform's HTTP API.
//
// The API is deliberately frontend-agnostic: the Vue admin app is a separate
// project that talks to these endpoints over CORS (dev) or a reverse proxy
// (production). Nothing here renders HTML.
package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/auth"
	"github.com/tm00013/trading/backend/internal/quantcli"
	"github.com/tm00013/trading/backend/internal/secretbox"
	"github.com/tm00013/trading/backend/internal/store"
)

const (
	defaultMaxBodyBytes = 256 << 10
	Version             = "0.4.0"
)

// Quant is the subset of the Python CLI the HTTP layer needs. Keeping it an
// interface lets handler tests run without spawning Python.
type Quant interface {
	Strategies(ctx context.Context) (json.RawMessage, error)
	Backtest(ctx context.Context, req quantcli.BacktestRequest) (json.RawMessage, error)
	Klines(ctx context.Context, query quantcli.KlineQuery) (json.RawMessage, error)
	KlineSymbols(ctx context.Context, interval string) (json.RawMessage, error)
}

// UserStore is the user persistence the handlers need.
type UserStore interface {
	CountUsers(ctx context.Context) (int64, error)
	CreateUser(ctx context.Context, email, passwordHash, role string) (store.User, error)
	UserByEmail(ctx context.Context, email string) (store.User, error)
	UserByID(ctx context.Context, id int64) (store.User, error)
	ListUsers(ctx context.Context) ([]store.User, error)
}

// CredentialStore persists encrypted exchange keys.
type CredentialStore interface {
	UpsertCredentials(ctx context.Context, userID int64, exchange, label, apiKeyCipher, secretCipher, hint string) error
	GetCredentials(ctx context.Context, userID int64, exchange string) (store.Credentials, error)
	DeleteCredentials(ctx context.Context, userID int64, exchange string) error
}

// RunStore persists backtest history.
type RunStore interface {
	RecordRun(ctx context.Context, run store.Run) (int64, error)
	ListRuns(ctx context.Context, userID int64, limit int) ([]store.RunSummary, error)
	GetRun(ctx context.Context, userID, id int64) (store.Run, error)
}

type Config struct {
	AllowedOrigins      []string
	MaxBodyBytes        int64
	SessionCookieSecure bool

	Auth           *auth.Manager
	Users          UserStore
	Credentials    CredentialStore
	Runs           RunStore
	CredentialsBox *secretbox.Box
}

type Server struct {
	quant Quant
	log   *slog.Logger
	cfg   Config

	setupMu sync.Mutex
	mu      sync.Mutex
	sems    map[int64]chan struct{} // one running backtest per user
}

func New(quant Quant, logger *slog.Logger, cfg Config) *Server {
	if cfg.MaxBodyBytes <= 0 {
		cfg.MaxBodyBytes = defaultMaxBodyBytes
	}
	if cfg.Auth == nil {
		logger.Warn("authentication is disabled; this must only happen in tests")
	}
	return &Server{
		quant: quant,
		log:   logger,
		cfg:   cfg,
		sems:  make(map[int64]chan struct{}),
	}
}

// Router builds the Gin engine with middleware, routes and JSON 404s.
func (s *Server) Router() *gin.Engine {
	r := gin.New()
	r.Use(gin.Recovery(), requestLogger(s.log), cors(s.cfg.AllowedOrigins))

	api := r.Group("/api")
	api.GET("/health", s.handleHealth)
	api.GET("/auth/status", s.handleAuthStatus)
	api.POST("/auth/login", s.handleLogin)
	api.POST("/auth/bootstrap", s.handleBootstrap)
	api.POST("/auth/logout", s.handleLogout)

	secured := api.Group("")
	secured.Use(s.authMiddleware())
	secured.GET("/auth/me", s.handleMe)
	secured.GET("/strategies", s.handleStrategies)
	secured.GET("/klines/symbols", s.handleKlineSymbols)
	secured.GET("/klines", s.handleKlines)
	secured.POST("/backtests", s.handleBacktest)
	secured.GET("/backtests", s.handleListRuns)
	secured.GET("/backtests/:id", s.handleGetRun)
	secured.GET("/me/credentials", s.handleGetCredentials)
	secured.PUT("/me/credentials", s.handlePutCredentials)
	secured.DELETE("/me/credentials", s.handleDeleteCredentials)

	admin := secured.Group("")
	admin.Use(auth.RequireRole("admin"))
	admin.GET("/users", s.handleListUsers)
	admin.POST("/users", s.handleCreateUser)

	r.NoRoute(func(c *gin.Context) {
		c.JSON(http.StatusNotFound, gin.H{"error": "not found"})
	})
	return r
}

func (s *Server) authMiddleware() gin.HandlerFunc {
	if s.cfg.Auth != nil {
		return s.cfg.Auth.Middleware()
	}
	return func(c *gin.Context) { c.Next() }
}

func (s *Server) currentUser(c *gin.Context) (store.User, bool) {
	if s.cfg.Auth == nil {
		return store.User{ID: 1, Email: "test@local", Role: "admin", Status: "active"}, true
	}
	return auth.CurrentUser(c)
}

func (s *Server) handleHealth(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{
		"status":  "ok",
		"version": Version,
		"time":    time.Now().UTC().Format(time.RFC3339),
	})
}

func (s *Server) handleStrategies(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()

	payload, err := s.quant.Strategies(ctx)
	if err != nil {
		s.fail(c, "读取策略列表失败", err)
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

func (s *Server) handleBacktest(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	if !s.acquire(user.ID) {
		c.JSON(http.StatusConflict, gin.H{"error": "你已有一个回测在运行，请等待完成"})
		return
	}
	defer s.release(user.ID)

	var req quantcli.BacktestRequest
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	req.ReportGroup = fmt.Sprintf("user_%d", user.ID)

	started := time.Now()
	payload, err := s.quant.Backtest(c.Request.Context(), req)
	if err != nil {
		s.fail(c, "回测失败", err)
		return
	}
	s.recordRun(c, user.ID, req, payload)
	s.log.Info("backtest finished",
		"user_id", user.ID,
		"strategy", req.Strategy,
		"symbols", req.Symbols,
		"duration_ms", time.Since(started).Milliseconds(),
	)
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

func (s *Server) recordRun(c *gin.Context, userID int64, req quantcli.BacktestRequest, payload json.RawMessage) {
	if s.cfg.Runs == nil {
		return
	}
	var parsed struct {
		FinalEquity float64        `json:"final_equity"`
		Metrics     map[string]any `json:"metrics"`
	}
	_ = json.Unmarshal(payload, &parsed)

	var (
		totalReturn *float64
		finalEquity *float64
	)
	if value, ok := parsed.Metrics["total_return"].(float64); ok {
		totalReturn = &value
	}
	if parsed.FinalEquity != 0 {
		finalEquity = &parsed.FinalEquity
	}
	var reportDir string
	var report struct {
		ReportDir string `json:"report_dir"`
	}
	if json.Unmarshal(payload, &report) == nil {
		reportDir = report.ReportDir
	}
	symbolsJSON, _ := json.Marshal(req.Symbols)
	paramsJSON, _ := json.Marshal(req.Params)

	ctx, cancel := context.WithTimeout(context.WithoutCancel(c.Request.Context()), 5*time.Second)
	defer cancel()
	id, err := s.cfg.Runs.RecordRun(ctx, store.Run{
		UserID:      userID,
		Strategy:    req.Strategy,
		Symbols:     string(symbolsJSON),
		Params:      string(paramsJSON),
		ReportDir:   reportDir,
		TotalReturn: totalReturn,
		FinalEquity: finalEquity,
		ResultJSON:  string(payload),
	})
	if err != nil {
		s.log.Error("record backtest run failed", "user_id", userID, "err", err)
		return
	}
	s.log.Info("backtest recorded", "user_id", userID, "run_id", id)
}

func (s *Server) acquire(userID int64) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	sem := s.sems[userID]
	if sem == nil {
		sem = make(chan struct{}, 1)
		s.sems[userID] = sem
	}
	select {
	case sem <- struct{}{}:
		return true
	default:
		return false
	}
}

func (s *Server) release(userID int64) {
	s.mu.Lock()
	sem := s.sems[userID]
	s.mu.Unlock()
	if sem != nil {
		<-sem
	}
}

func (s *Server) decode(c *gin.Context, dst any) error {
	body := http.MaxBytesReader(c.Writer, c.Request.Body, s.cfg.MaxBodyBytes)
	decoder := json.NewDecoder(body)
	decoder.UseNumber()
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(dst); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("请求体只能包含一个 JSON 对象")
	}
	return nil
}

func (s *Server) fail(c *gin.Context, prefix string, err error) {
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
		c.JSON(status, gin.H{"error": cliErr.Message})
		return
	}
	s.log.Error("internal error", "err", err)
	c.JSON(http.StatusInternalServerError, gin.H{"error": prefix + ": " + err.Error()})
}

// cors reflects known origins and permits cookies. Mutating requests carrying
// an unknown Origin are rejected, which also blocks most cross-site CSRF.
func cors(origins []string) gin.HandlerFunc {
	allowed := make(map[string]struct{}, len(origins))
	for _, origin := range origins {
		origin = strings.TrimSpace(origin)
		if origin != "" {
			allowed[origin] = struct{}{}
		}
	}

	return func(c *gin.Context) {
		origin := c.GetHeader("Origin")
		if origin != "" {
			_, listed := allowed[origin]
			if listed || sameHost(c, origin) {
				c.Header("Access-Control-Allow-Origin", origin)
				c.Header("Vary", "Origin")
				c.Header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
				c.Header("Access-Control-Allow-Headers", "Content-Type, Authorization")
				c.Header("Access-Control-Allow-Credentials", "true")
				c.Header("Access-Control-Max-Age", "600")
			} else if c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead && c.Request.Method != http.MethodOptions {
				c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "origin not allowed"})
				return
			}
		}
		if c.Request.Method == http.MethodOptions {
			c.AbortWithStatus(http.StatusNoContent)
			return
		}
		c.Next()
	}
}

// sameHost lets nginx serve the Vue app and /api from one domain without
// requiring the operator to list the public origin in CORS_ORIGINS.
func sameHost(c *gin.Context, origin string) bool {
	parsed, err := url.Parse(origin)
	if err != nil || parsed.Host == "" {
		return false
	}
	host := c.GetHeader("X-Forwarded-Host")
	if host == "" {
		host = c.Request.Host
	}
	return strings.EqualFold(parsed.Host, host)
}

func requestLogger(logger *slog.Logger) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		c.Next()
		logger.Info("request",
			"method", c.Request.Method,
			"path", c.Request.URL.Path,
			"status", c.Writer.Status(),
			"duration_ms", time.Since(start).Milliseconds(),
			"client", c.ClientIP(),
		)
	}
}
