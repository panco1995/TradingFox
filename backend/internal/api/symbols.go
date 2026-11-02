package api

import (
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// handleListSymbols returns the collector's subscription list.
func (s *Server) handleListSymbols(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()

	payload, err := s.quant.Symbols(ctx, "list", "", "")
	if err != nil {
		s.fail(c, "读取交易对失败", err)
		return
	}
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

// handleAddSymbol validates the pair against the exchange before saving it.
//
// Everything is delegated to Python so the validation rules live in one place;
// the reply carries the exchange's own status (TRADING, BREAK, ...).
func (s *Server) handleAddSymbol(c *gin.Context) {
	var req struct {
		Symbol string `json:"symbol"`
	}
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	if strings.TrimSpace(req.Symbol) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请输入交易对，例如 SOLUSDT"})
		return
	}

	updatedBy := "admin"
	if user, ok := s.currentUser(c); ok {
		updatedBy = fmt.Sprintf("user_%d", user.ID)
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 45*time.Second)
	defer cancel()

	symbol := strings.ToUpper(strings.TrimSpace(req.Symbol))
	payload, err := s.quant.Symbols(ctx, "add", symbol, updatedBy)
	if err != nil {
		// A rejected symbol is the caller's mistake, not an upstream failure.
		s.fail(c, "添加交易对失败", err)
		return
	}

	s.log.Info("symbol added", "symbol", symbol, "by", updatedBy)
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}

// handleRemoveSymbol stops collecting a pair. Existing Parquet files stay.
func (s *Server) handleRemoveSymbol(c *gin.Context) {
	symbol := strings.ToUpper(strings.TrimSpace(c.Param("symbol")))
	if symbol == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请输入交易对"})
		return
	}

	updatedBy := "admin"
	if user, ok := s.currentUser(c); ok {
		updatedBy = fmt.Sprintf("user_%d", user.ID)
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()

	payload, err := s.quant.Symbols(ctx, "remove", symbol, updatedBy)
	if err != nil {
		s.fail(c, "移除交易对失败", err)
		return
	}

	s.log.Info("symbol removed", "symbol", symbol, "by", updatedBy)
	c.Data(http.StatusOK, "application/json; charset=utf-8", payload)
}
