package auth

import (
	"testing"
	"time"

	"github.com/tm00013/trading/backend/internal/store"
)

func TestPasswordRoundTrip(t *testing.T) {
	hash, err := HashPassword("correct horse battery staple")
	if err != nil {
		t.Fatal(err)
	}
	if !CheckPassword(hash, "correct horse battery staple") {
		t.Fatal("valid password rejected")
	}
	if CheckPassword(hash, "wrong") {
		t.Fatal("wrong password accepted")
	}
}

func TestSecretFromEnv(t *testing.T) {
	if _, ephemeral, err := SecretFromEnv(""); err != nil || !ephemeral {
		t.Fatalf("empty secret: ephemeral=%v err=%v", ephemeral, err)
	}
	raw := "raw-secret-!-0123456789abcdef"
	secret, ephemeral, err := SecretFromEnv(raw)
	if err != nil || ephemeral {
		t.Fatalf("raw secret: ephemeral=%v err=%v", ephemeral, err)
	}
	if string(secret) != raw {
		t.Fatalf("secret = %q", secret)
	}
	if _, _, err := SecretFromEnv("short"); err == nil {
		t.Fatal("short secret should fail")
	}
}

func TestIssueAndParse(t *testing.T) {
	manager, err := NewManager(nil, []byte("0123456789abcdef0123456789abcdef"), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	token, expires, err := manager.Issue(store.User{ID: 42, Email: "a@b.c", Role: "user"})
	if err != nil {
		t.Fatal(err)
	}
	if time.Until(expires) <= 0 {
		t.Fatal("expired token")
	}
	id, err := manager.parse(token)
	if err != nil {
		t.Fatal(err)
	}
	if id != 42 {
		t.Fatalf("id = %d", id)
	}
	if _, err := manager.parse(token + "x"); err == nil {
		t.Fatal("tampered token accepted")
	}
}

func TestShortSecretRejected(t *testing.T) {
	if _, err := NewManager(nil, []byte("short"), time.Hour); err == nil {
		t.Fatal("expected an error")
	}
}
