package api

import (
	"errors"
	"net/http"
	"net/mail"
	"strings"
	"time"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/auth"
	"github.com/tm00013/trading/backend/internal/store"
)

const (
	minPasswordLength = 8
	maxPasswordLength = 72 // bcrypt input limit
)

type userDTO struct {
	ID        int64     `json:"id"`
	Email     string    `json:"email"`
	Role      string    `json:"role"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
}

func toUserDTO(user store.User) userDTO {
	return userDTO{
		ID:        user.ID,
		Email:     user.Email,
		Role:      user.Role,
		Status:    user.Status,
		CreatedAt: user.CreatedAt,
	}
}

type emailPasswordRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

func (s *Server) handleAuthStatus(c *gin.Context) {
	if s.cfg.Users == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "用户存储未配置"})
		return
	}
	count, err := s.cfg.Users.CountUsers(c.Request.Context())
	if err != nil {
		s.log.Error("count users failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "读取系统状态失败"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"needs_setup": count == 0})
}

func (s *Server) handleBootstrap(c *gin.Context) {
	if s.cfg.Users == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "用户存储未配置"})
		return
	}

	s.setupMu.Lock()
	defer s.setupMu.Unlock()

	count, err := s.cfg.Users.CountUsers(c.Request.Context())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "读取系统状态失败"})
		return
	}
	if count > 0 {
		c.JSON(http.StatusConflict, gin.H{"error": "系统已初始化，请联系管理员创建账号"})
		return
	}

	var req emailPasswordRequest
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	email, password, err := validateCredentials(req.Email, req.Password)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	hash, err := auth.HashPassword(password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "密码处理失败"})
		return
	}
	user, err := s.cfg.Users.CreateUser(c.Request.Context(), email, hash, "admin")
	if err != nil {
		if errors.Is(err, store.ErrEmailTaken) {
			c.JSON(http.StatusConflict, gin.H{"error": "该邮箱已被注册"})
			return
		}
		s.log.Error("bootstrap user failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "创建管理员失败"})
		return
	}
	s.issueSession(c, user)
	c.JSON(http.StatusCreated, gin.H{"user": toUserDTO(user)})
}

func (s *Server) handleLogin(c *gin.Context) {
	if s.cfg.Users == nil || s.cfg.Auth == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "登录服务未配置"})
		return
	}

	var req emailPasswordRequest
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	email := normalizeEmail(req.Email)
	user, err := s.cfg.Users.UserByEmail(c.Request.Context(), email)
	if errors.Is(err, store.ErrNotFound) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "邮箱或密码错误"})
		return
	}
	if err != nil {
		s.log.Error("lookup user failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "登录失败，请稍后重试"})
		return
	}
	if !auth.CheckPassword(user.PasswordHash, req.Password) {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "邮箱或密码错误"})
		return
	}
	if user.Status != "active" {
		c.JSON(http.StatusForbidden, gin.H{"error": "账号已被禁用"})
		return
	}
	s.issueSession(c, user)
	c.JSON(http.StatusOK, gin.H{"user": toUserDTO(user)})
}

func (s *Server) handleLogout(c *gin.Context) {
	s.clearSession(c)
	c.Status(http.StatusNoContent)
}

func (s *Server) handleMe(c *gin.Context) {
	user, ok := s.currentUser(c)
	if !ok {
		c.JSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
		return
	}
	c.JSON(http.StatusOK, gin.H{"user": toUserDTO(user)})
}

func (s *Server) issueSession(c *gin.Context, user store.User) {
	if s.cfg.Auth == nil {
		return
	}
	token, expires, err := s.cfg.Auth.Issue(user)
	if err != nil {
		s.log.Error("issue session failed", "err", err)
		return
	}
	maxAge := int(time.Until(expires).Seconds())
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(auth.SessionCookie, token, maxAge, "/", "", s.cfg.SessionCookieSecure, true)
}

func (s *Server) clearSession(c *gin.Context) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(auth.SessionCookie, "", -1, "/", "", s.cfg.SessionCookieSecure, true)
}

func validateCredentials(email, password string) (string, string, error) {
	normalized := normalizeEmail(email)
	if normalized == "" {
		return "", "", errors.New("请输入有效邮箱")
	}
	if len(password) < minPasswordLength {
		return "", "", errors.New("密码至少 8 位")
	}
	if len(password) > maxPasswordLength {
		return "", "", errors.New("密码不能超过 72 位")
	}
	return normalized, password, nil
}

func normalizeEmail(raw string) string {
	email := strings.ToLower(strings.TrimSpace(raw))
	if email == "" || len(email) > 255 {
		return ""
	}
	parsed, err := mail.ParseAddress(email)
	if err != nil || parsed.Address != email {
		return ""
	}
	return email
}
