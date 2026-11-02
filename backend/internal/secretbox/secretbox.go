// Package secretbox encrypts exchange API keys at rest with AES-256-GCM.
package secretbox

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/base64"
	"errors"
	"fmt"
	"io"
)

type Box struct {
	aead cipher.AEAD
}

// New decodes a base64 32-byte key (generate with `openssl rand -base64 32`).
func New(encodedKey string) (*Box, error) {
	key, err := base64.StdEncoding.DecodeString(encodedKey)
	if err != nil {
		return nil, fmt.Errorf("CREDENTIALS_KEY must be base64: %w", err)
	}
	if len(key) != 32 {
		return nil, fmt.Errorf("CREDENTIALS_KEY must decode to 32 bytes, got %d", len(key))
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &Box{aead: aead}, nil
}

// Seal returns base64(nonce || ciphertext).
func (b *Box) Seal(plain string) (string, error) {
	nonce := make([]byte, b.aead.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}
	out := b.aead.Seal(nonce, nonce, []byte(plain), nil)
	return base64.StdEncoding.EncodeToString(out), nil
}

// Open reverses Seal.
func (b *Box) Open(encoded string) (string, error) {
	raw, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return "", err
	}
	if len(raw) < b.aead.NonceSize() {
		return "", errors.New("ciphertext too short")
	}
	nonce, body := raw[:b.aead.NonceSize()], raw[b.aead.NonceSize():]
	plain, err := b.aead.Open(nil, nonce, body, nil)
	if err != nil {
		return "", err
	}
	return string(plain), nil
}
