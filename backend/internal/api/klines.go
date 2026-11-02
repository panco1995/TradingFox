package api

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/quantcli"
)

func (s *Server) handleKlines(c *gin.Context) {
	days, err := parseBoundedInt(c.Query("days"), 2, 1, 366)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "天数需要在 1 到 366 之间"})
		return
	}
	limit, err := parseBoundedInt(c.Query("limit"), 10_000, 1, 20_000)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "K 线数量需要在 1 到 20000 之间"})
		return
	}

	query := quantcli.KlineQuery{
		Symbol:   c.Query("symbol"),
		Interval: c.DefaultQuery("interval", "1m"),
		Days:     days,
		Start:    strings.TrimSpace(c.Query("start")),
		End:      strings.TrimSpace(c.Query("end")),
		Limit:    limit,
	}
	if err := query.Validate(); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	payload, err := s.quant.Klines(ctx, query)
	if err != nil {
		s.fail(c, "读取 K 线失败", err)
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

func (s *Server) handleKlineSymbols(c *gin.Context) {
	interval := c.DefaultQuery("interval", "1m")
	if err := quantcli.ValidateInterval(interval); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	payload, err := s.quant.KlineSymbols(ctx, interval)
	if err != nil {
		s.fail(c, "读取交易对失败", err)
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

func parseBoundedInt(raw string, fallback, min, max int) (int, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return fallback, nil
	}
	n, err := strconv.Atoi(raw)
	if err != nil || n < min || n > max {
		return 0, errors.New("out of range")
	}
	return n, nil
}
