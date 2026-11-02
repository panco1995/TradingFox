package api

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/store"
)

const exchangeBinance = "BINANCE"

type putCredentialsRequest struct {
	APIKey string `json:"api_key"`
	Secret string `json:"secret"`
	Label  string `json:"label"`
}

type credentialsDTO struct {
	Exchange   string     `json:"exchange"`
	Configured bool       `json:"configured"`
	APIKeyHint string     `json:"api_key_hint,omitempty"`
	Label      string     `json:"label,omitempty"`
	UpdatedAt  *time.Time `json:"updated_at,omitempty"`
}

func (s *Server) credentialsReady(c *gin.Context) bool {
	if s.cfg.Credentials == nil || s.cfg.CredentialsBox == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{
			"error": "未配置 CREDENTIALS_KEY，服务端无法加密保存 API Key",
		})
		return false
	}
	return true
}

func (s *Server) handleGetCredentials(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	if !s.credentialsReady(c) {
		return
	}
	creds, err := s.cfg.Credentials.GetCredentials(c.Request.Context(), user.ID, exchangeBinance)
	if errors.Is(err, store.ErrNotFound) {
		c.JSON(http.StatusOK, credentialsDTO{Exchange: exchangeBinance, Configured: false})
		return
	}
	if err != nil {
		s.log.Error("get credentials failed", "user_id", user.ID, "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "读取 API Key 失败"})
		return
	}
	c.JSON(http.StatusOK, credentialsDTO{
		Exchange:   creds.Exchange,
		Configured: true,
		APIKeyHint: creds.APIKeyHint,
		Label:      creds.Label,
		UpdatedAt:  &creds.UpdatedAt,
	})
}

func (s *Server) handlePutCredentials(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	if !s.credentialsReady(c) {
		return
	}

	var req putCredentialsRequest
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	apiKey := strings.TrimSpace(req.APIKey)
	secret := strings.TrimSpace(req.Secret)
	if apiKey == "" || secret == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "API Key 和 Secret 都不能为空"})
		return
	}
	if len(apiKey) > 256 || len(secret) > 256 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "API Key 或 Secret 过长"})
		return
	}
	label := strings.TrimSpace(req.Label)
	if len(label) > 64 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "备注不能超过 64 个字符"})
		return
	}

	apiKeyCipher, err := s.cfg.CredentialsBox.Seal(apiKey)
	if err != nil {
		s.log.Error("seal api key failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "加密 API Key 失败"})
		return
	}
	secretCipher, err := s.cfg.CredentialsBox.Seal(secret)
	if err != nil {
		s.log.Error("seal secret failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "加密 Secret 失败"})
		return
	}
	if err := s.cfg.Credentials.UpsertCredentials(
		c.Request.Context(), user.ID, exchangeBinance, label, apiKeyCipher, secretCipher, maskKey(apiKey),
	); err != nil {
		s.log.Error("save credentials failed", "user_id", user.ID, "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "保存 API Key 失败"})
		return
	}

	if stored, err := s.cfg.Credentials.GetCredentials(c.Request.Context(), user.ID, exchangeBinance); err == nil {
		c.JSON(http.StatusOK, credentialsDTO{
			Exchange:   stored.Exchange,
			Configured: true,
			APIKeyHint: stored.APIKeyHint,
			Label:      stored.Label,
			UpdatedAt:  &stored.UpdatedAt,
		})
		return
	}
	now := time.Now().UTC()
	c.JSON(http.StatusOK, credentialsDTO{
		Exchange:   exchangeBinance,
		Configured: true,
		APIKeyHint: maskKey(apiKey),
		Label:      label,
		UpdatedAt:  &now,
	})
}

func (s *Server) handleDeleteCredentials(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	if s.cfg.Credentials == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "凭据存储未配置"})
		return
	}
	if err := s.cfg.Credentials.DeleteCredentials(c.Request.Context(), user.ID, exchangeBinance); err != nil {
		s.log.Error("delete credentials failed", "user_id", user.ID, "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "删除 API Key 失败"})
		return
	}
	c.Status(http.StatusNoContent)
}

func maskKey(key string) string {
	if len(key) <= 8 {
		return "••••"
	}
	return key[:4] + "…" + key[len(key)-4:]
}
