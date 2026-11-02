// Package main starts the trading platform HTTP API.
//
// It uses Gin and serves JSON only. The Vue admin app is a separate project
// under ../frontend and is not embedded here.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/tm00013/trading/backend/internal/api"
	"github.com/tm00013/trading/backend/internal/auth"
	"github.com/tm00013/trading/backend/internal/quantcli"
	"github.com/tm00013/trading/backend/internal/secretbox"
	"github.com/tm00013/trading/backend/internal/store"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	quant, err := quantcli.Default()
	if err != nil {
		logger.Error("quant CLI unavailable", "err", err)
		os.Exit(1)
	}

	db, err := store.OpenFromEnv()
	if err != nil {
		logger.Error("database unavailable", "err", err)
		os.Exit(1)
	}
	defer db.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	if err := db.Migrate(ctx); err != nil {
		cancel()
		logger.Error("schema migration failed", "err", err)
		os.Exit(1)
	}
	cancel()

	secret, ephemeral, err := auth.SecretFromEnv(os.Getenv("AUTH_SECRET"))
	if err != nil {
		logger.Error("invalid AUTH_SECRET", "err", err)
		os.Exit(1)
	}
	if ephemeral {
		logger.Warn("AUTH_SECRET is not set; using an ephemeral key (all sessions reset on restart)")
	}
	authManager, err := auth.NewManager(db, secret, 7*24*time.Hour)
	if err != nil {
		logger.Error("cannot create auth manager", "err", err)
		os.Exit(1)
	}

	var credBox *secretbox.Box
	if raw := os.Getenv("CREDENTIALS_KEY"); raw != "" {
		credBox, err = secretbox.New(raw)
		if err != nil {
			logger.Error("invalid CREDENTIALS_KEY", "err", err)
			os.Exit(1)
		}
	} else {
		logger.Warn("CREDENTIALS_KEY is not set; exchange credential endpoints are disabled")
	}

	cfg := api.Config{
		AllowedOrigins:      splitEnv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"),
		SessionCookieSecure: envBool("SESSION_COOKIE_SECURE", false),
		Auth:                authManager,
		Users:               db,
		Credentials:         db,
		Runs:                db,
		CredentialsBox:      credBox,
	}
	handler := api.New(quant, logger, cfg).Router()

	addr := netAddr()
	srv := &http.Server{
		Addr:              addr,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      6 * time.Minute, // backtests are synchronous
		IdleTimeout:       60 * time.Second,
	}

	errc := make(chan error, 1)
	go func() {
		logger.Info("api listening", "addr", addr, "version", api.Version, "python", quant.Python)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errc <- err
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)

	select {
	case err := <-errc:
		logger.Error("server failed", "err", err)
		os.Exit(1)
	case sig := <-stop:
		logger.Info("shutting down", "signal", sig.String())
	}

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		logger.Error("graceful shutdown failed", "err", err)
	}
	logger.Info("bye")
}

func netAddr() string {
	host := os.Getenv("HOST")
	if host == "" {
		host = "127.0.0.1"
	}
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}
	return host + ":" + port
}

func splitEnv(key, fallback string) []string {
	raw := os.Getenv(key)
	if raw == "" {
		raw = fallback
	}
	parts := strings.Split(raw, ",")
	out := make([]string, 0, len(parts))
	for _, part := range parts {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}

func envBool(key string, fallback bool) bool {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := strconv.ParseBool(raw)
	if err != nil {
		return fallback
	}
	return value
}
