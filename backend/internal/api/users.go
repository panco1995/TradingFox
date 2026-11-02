package api

import (
	"errors"
	"net/http"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/auth"
	"github.com/tm00013/trading/backend/internal/store"
)

type createUserRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

func (s *Server) handleListUsers(c *gin.Context) {
	if s.cfg.Users == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "用户存储未配置"})
		return
	}
	users, err := s.cfg.Users.ListUsers(c.Request.Context())
	if err != nil {
		s.log.Error("list users failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "读取用户列表失败"})
		return
	}
	out := make([]userDTO, 0, len(users))
	for _, user := range users {
		out = append(out, toUserDTO(user))
	}
	c.JSON(http.StatusOK, out)
}

func (s *Server) handleCreateUser(c *gin.Context) {
	if s.cfg.Users == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "用户存储未配置"})
		return
	}

	var req createUserRequest
	if err := s.decode(c, &req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "请求体不合法: " + err.Error()})
		return
	}
	email, password, err := validateCredentials(req.Email, req.Password)
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	role := req.Role
	if role == "" {
		role = "user"
	}
	if role != "admin" && role != "user" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "角色只能是 admin 或 user"})
		return
	}

	hash, err := auth.HashPassword(password)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "密码处理失败"})
		return
	}
	user, err := s.cfg.Users.CreateUser(c.Request.Context(), email, hash, role)
	if err != nil {
		if errors.Is(err, store.ErrEmailTaken) {
			c.JSON(http.StatusConflict, gin.H{"error": "该邮箱已被注册"})
			return
		}
		s.log.Error("create user failed", "err", err)
		c.JSON(http.StatusInternalServerError, gin.H{"error": "创建用户失败"})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"user": toUserDTO(user)})
}
