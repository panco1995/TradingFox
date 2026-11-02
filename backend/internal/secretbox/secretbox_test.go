package secretbox

import (
	"bytes"
	"encoding/base64"
	"testing"
)

func testKey() string { return base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{9}, 32)) }

func TestSealOpenRoundTrip(t *testing.T) {
	box, err := New(testKey())
	if err != nil {
		t.Fatal(err)
	}
	secret := "binance-secret-key-value"

	first, err := box.Seal(secret)
	if err != nil {
		t.Fatal(err)
	}
	second, err := box.Seal(secret)
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("two seals should use different nonces")
	}

	plain, err := box.Open(first)
	if err != nil {
		t.Fatal(err)
	}
	if plain != secret {
		t.Fatalf("plain = %q", plain)
	}
}

func TestNewRejectsWrongKeyLength(t *testing.T) {
	if _, err := New(base64.StdEncoding.EncodeToString([]byte("short"))); err == nil {
		t.Fatal("expected an error")
	}
}

func TestOpenRejectsTamperedCiphertext(t *testing.T) {
	box, err := New(testKey())
	if err != nil {
		t.Fatal(err)
	}
	sealed, err := box.Seal("secret")
	if err != nil {
		t.Fatal(err)
	}
	raw, err := base64.StdEncoding.DecodeString(sealed)
	if err != nil {
		t.Fatal(err)
	}
	raw[len(raw)-1] ^= 0xff
	if _, err := box.Open(base64.StdEncoding.EncodeToString(raw)); err == nil {
		t.Fatal("tampered ciphertext must not open")
	}
}
