// Package auth handles password hashing, signed session tokens and Gin
// middleware that resolves the current user from a cookie or bearer token.
package auth

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"

	"github.com/tm00013/trading/backend/internal/store"
)

const (
	SessionCookie = "trading_session"
	Issuer        = "trading-api"
	userKey       = "auth.user"
)

// UserStore is the subset of the database the middleware needs.
type UserStore interface {
	UserByID(ctx context.Context, id int64) (store.User, error)
}

// Manager issues and verifies sessions.
type Manager struct {
	store  UserStore
	secret []byte
	ttl    time.Duration
}

func NewManager(users UserStore, secret []byte, ttl time.Duration) (*Manager, error) {
	if len(secret) < 16 {
		return nil, errors.New("auth secret must be at least 16 bytes")
	}
	if ttl <= 0 {
		ttl = 7 * 24 * time.Hour
	}
	return &Manager{store: users, secret: secret, ttl: ttl}, nil
}

// RandomSecret returns a base64 encoded 32-byte key, used when AUTH_SECRET is
// not configured. Sessions then reset on restart, which is acceptable for dev.
func RandomSecret() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return base64.StdEncoding.EncodeToString(buf), nil
}

// SecretFromEnv decodes AUTH_SECRET (base64 or raw). An empty value returns a
// fresh random secret and done=false so the caller can warn.
func SecretFromEnv(raw string) (secret []byte, ephemeral bool, err error) {
	if strings.TrimSpace(raw) == "" {
		buf := make([]byte, 32)
		if _, err := rand.Read(buf); err != nil {
			return nil, false, err
		}
		return buf, true, nil
	}
	if decoded, decodeErr := base64.StdEncoding.DecodeString(raw); decodeErr == nil && len(decoded) >= 16 {
		return decoded, false, nil
	}
	if len(raw) < 16 {
		return nil, false, errors.New("AUTH_SECRET must be at least 16 characters or valid base64")
	}
	return []byte(raw), false, nil
}

func HashPassword(password string) (string, error) {
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(hash), err
}

func CheckPassword(hash, password string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(password)) == nil
}

type claims struct {
	Email string `json:"email"`
	Role  string `json:"role"`
	jwt.RegisteredClaims
}

// Issue creates a signed token and its expiry.
func (m *Manager) Issue(user store.User) (string, time.Time, error) {
	now := time.Now().UTC()
	expires := now.Add(m.ttl)
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims{
		Email: user.Email,
		Role:  user.Role,
		RegisteredClaims: jwt.RegisteredClaims{
			Issuer:    Issuer,
			Subject:   strconv.FormatInt(user.ID, 10),
			IssuedAt:  jwt.NewNumericDate(now),
			NotBefore: jwt.NewNumericDate(now.Add(-30 * time.Second)),
			ExpiresAt: jwt.NewNumericDate(expires),
		},
	})
	signed, err := token.SignedString(m.secret)
	return signed, expires, err
}

func (m *Manager) parse(token string) (int64, error) {
	parsed, err := jwt.ParseWithClaims(token, &claims{}, func(t *jwt.Token) (any, error) {
		if t.Method != jwt.SigningMethodHS256 {
			return nil, fmt.Errorf("unexpected signing method %s", t.Method.Alg())
		}
		return m.secret, nil
	}, jwt.WithIssuer(Issuer), jwt.WithExpirationRequired())
	if err != nil || !parsed.Valid {
		return 0, errors.New("invalid session")
	}
	payload, ok := parsed.Claims.(*claims)
	if !ok {
		return 0, errors.New("invalid session")
	}
	id, err := strconv.ParseInt(payload.Subject, 10, 64)
	if err != nil || id <= 0 {
		return 0, errors.New("invalid session")
	}
	return id, nil
}

// Middleware rejects anonymous requests and stores the loaded user in the
// request context. It always reloads from the database so disabling an account
// takes effect immediately, without waiting for the token to expire.
func (m *Manager) Middleware() gin.HandlerFunc {
	return func(c *gin.Context) {
		token := bearerToken(c.GetHeader("Authorization"))
		if token == "" {
			if cookie, err := c.Cookie(SessionCookie); err == nil {
				token = cookie
			}
		}
		if token == "" {
			abortUnauthorized(c)
			return
		}
		userID, err := m.parse(token)
		if err != nil {
			abortUnauthorized(c)
			return
		}
		user, err := m.store.UserByID(c.Request.Context(), userID)
		if err != nil || user.Status != "active" {
			abortUnauthorized(c)
			return
		}
		c.Set(userKey, user)
		c.Next()
	}
}

// CurrentUser returns the user placed in the context by Middleware.
func CurrentUser(c *gin.Context) (store.User, bool) {
	value, ok := c.Get(userKey)
	if !ok {
		return store.User{}, false
	}
	user, ok := value.(store.User)
	return user, ok
}

// RequireRole is a second gate for admin-only routes.
func RequireRole(role string) gin.HandlerFunc {
	return func(c *gin.Context) {
		user, ok := CurrentUser(c)
		if !ok {
			abortUnauthorized(c)
			return
		}
		if user.Role != role {
			c.AbortWithStatusJSON(http.StatusForbidden, gin.H{"error": "没有权限执行该操作"})
			return
		}
		c.Next()
	}
}

func bearerToken(header string) string {
	const prefix = "Bearer "
	if len(header) > len(prefix) && strings.EqualFold(header[:len(prefix)], prefix) {
		return strings.TrimSpace(header[len(prefix):])
	}
	return ""
}

func abortUnauthorized(c *gin.Context) {
	c.AbortWithStatusJSON(http.StatusUnauthorized, gin.H{"error": "请先登录"})
}
