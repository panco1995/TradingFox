package api

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/tm00013/trading/backend/internal/auth"
	"github.com/tm00013/trading/backend/internal/secretbox"
	"github.com/tm00013/trading/backend/internal/store"
)

type fakeDB struct {
	users    map[int64]store.User
	nextUser int64
	creds    map[int64]store.Credentials
	runs     []store.Run
	nextRun  int64
}

func newFakeDB() *fakeDB {
	return &fakeDB{
		users: make(map[int64]store.User),
		creds: make(map[int64]store.Credentials),
	}
}

func (f *fakeDB) CountUsers(context.Context) (int64, error) { return int64(len(f.users)), nil }

func (f *fakeDB) CreateUser(_ context.Context, email, hash, role string) (store.User, error) {
	for _, user := range f.users {
		if user.Email == email {
			return store.User{}, store.ErrEmailTaken
		}
	}
	f.nextUser++
	user := store.User{
		ID:           f.nextUser,
		Email:        email,
		PasswordHash: hash,
		Role:         role,
		Status:       "active",
		CreatedAt:    time.Now().UTC(),
	}
	f.users[user.ID] = user
	return user, nil
}

func (f *fakeDB) UserByEmail(_ context.Context, email string) (store.User, error) {
	for _, user := range f.users {
		if user.Email == email {
			return user, nil
		}
	}
	return store.User{}, store.ErrNotFound
}

func (f *fakeDB) UserByID(_ context.Context, id int64) (store.User, error) {
	user, ok := f.users[id]
	if !ok {
		return store.User{}, store.ErrNotFound
	}
	return user, nil
}

func (f *fakeDB) ListUsers(context.Context) ([]store.User, error) {
	out := make([]store.User, 0, len(f.users))
	for id := int64(1); id <= f.nextUser; id++ {
		if user, ok := f.users[id]; ok {
			out = append(out, user)
		}
	}
	return out, nil
}

func (f *fakeDB) UpsertCredentials(_ context.Context, userID int64, exchange, label, apiKeyCipher, secretCipher, hint string) error {
	f.creds[userID] = store.Credentials{
		UserID:       userID,
		Exchange:     exchange,
		Label:        label,
		APIKeyCipher: apiKeyCipher,
		SecretCipher: secretCipher,
		APIKeyHint:   hint,
		UpdatedAt:    time.Now().UTC(),
	}
	return nil
}

func (f *fakeDB) GetCredentials(_ context.Context, userID int64, exchange string) (store.Credentials, error) {
	creds, ok := f.creds[userID]
	if !ok || creds.Exchange != exchange {
		return store.Credentials{}, store.ErrNotFound
	}
	return creds, nil
}

func (f *fakeDB) DeleteCredentials(_ context.Context, userID int64, exchange string) error {
	if creds, ok := f.creds[userID]; ok && creds.Exchange == exchange {
		delete(f.creds, userID)
	}
	return nil
}

func (f *fakeDB) RecordRun(_ context.Context, run store.Run) (int64, error) {
	f.nextRun++
	run.ID = f.nextRun
	run.CreatedAt = time.Now().UTC()
	f.runs = append(f.runs, run)
	return run.ID, nil
}

func (f *fakeDB) ListRuns(_ context.Context, userID int64, limit int) ([]store.RunSummary, error) {
	var out []store.RunSummary
	for i := len(f.runs) - 1; i >= 0 && len(out) < limit; i-- {
		run := f.runs[i]
		if run.UserID != userID {
			continue
		}
		out = append(out, store.RunSummary{
			ID:          run.ID,
			Strategy:    run.Strategy,
			Symbols:     run.Symbols,
			ReportDir:   run.ReportDir,
			TotalReturn: run.TotalReturn,
			FinalEquity: run.FinalEquity,
			CreatedAt:   run.CreatedAt,
		})
	}
	return out, nil
}

func (f *fakeDB) GetRun(_ context.Context, userID, id int64) (store.Run, error) {
	for _, run := range f.runs {
		if run.ID == id && run.UserID == userID {
			return run, nil
		}
	}
	return store.Run{}, store.ErrNotFound
}

func newAuthTestServer(t *testing.T, db *fakeDB, quant Quant) *Server {
	t.Helper()
	manager, err := auth.NewManager(db, []byte("0123456789abcdef0123456789abcdef"), time.Hour)
	if err != nil {
		t.Fatal(err)
	}
	box, err := secretbox.New(base64.StdEncoding.EncodeToString(bytes.Repeat([]byte{7}, 32)))
	if err != nil {
		t.Fatal(err)
	}
	return New(quant, slog.New(slog.NewTextHandler(io.Discard, nil)), Config{
		AllowedOrigins: []string{"http://localhost:5173"},
		Auth:           manager,
		Users:          db,
		Credentials:    db,
		Runs:           db,
		CredentialsBox: box,
	})
}

func doAuthRequest(handler http.Handler, method, path, body string, cookie *http.Cookie) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	if cookie != nil {
		req.AddCookie(cookie)
	}
	handler.ServeHTTP(rec, req)
	return rec
}

func sessionFrom(t *testing.T, rec *httptest.ResponseRecorder) *http.Cookie {
	t.Helper()
	for _, cookie := range rec.Result().Cookies() {
		if cookie.Name == auth.SessionCookie {
			return cookie
		}
	}
	t.Fatalf("no %s cookie in response: %v", auth.SessionCookie, rec.Result().Cookies())
	return nil
}

func bootstrapAdmin(t *testing.T, server *Server) *http.Cookie {
	t.Helper()
	rec := doAuthRequest(server.Router(), http.MethodPost, "/api/auth/bootstrap",
		`{"email":"admin@example.com","password":"password123"}`, nil)
	if rec.Code != http.StatusCreated {
		t.Fatalf("bootstrap status = %d body = %s", rec.Code, rec.Body)
	}
	return sessionFrom(t, rec)
}

func login(t *testing.T, server *Server, email, password string) *http.Cookie {
	t.Helper()
	rec := doAuthRequest(server.Router(), http.MethodPost, "/api/auth/login",
		`{"email":"`+email+`","password":"`+password+`"}`, nil)
	if rec.Code != http.StatusOK {
		t.Fatalf("login status = %d body = %s", rec.Code, rec.Body)
	}
	return sessionFrom(t, rec)
}

func TestAuthBootstrapAndMe(t *testing.T) {
	db := newFakeDB()
	server := newAuthTestServer(t, db, &fakeQuant{})
	router := server.Router()

	status := doAuthRequest(router, http.MethodGet, "/api/auth/status", "", nil)
	if !strings.Contains(status.Body.String(), `"needs_setup":true`) {
		t.Fatalf("status = %s", status.Body)
	}

	cookie := bootstrapAdmin(t, server)

	me := doAuthRequest(router, http.MethodGet, "/api/auth/me", "", cookie)
	if me.Code != http.StatusOK {
		t.Fatalf("me status = %d body = %s", me.Code, me.Body)
	}
	var payload struct {
		User userDTO `json:"user"`
	}
	if err := json.Unmarshal(me.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.User.Email != "admin@example.com" || payload.User.Role != "admin" {
		t.Fatalf("user = %+v", payload.User)
	}

	again := doAuthRequest(router, http.MethodPost, "/api/auth/bootstrap",
		`{"email":"other@example.com","password":"password123"}`, nil)
	if again.Code != http.StatusConflict {
		t.Fatalf("second bootstrap status = %d", again.Code)
	}
}

func TestAuthProtectedRoutesRequireLogin(t *testing.T) {
	db := newFakeDB()
	server := newAuthTestServer(t, db, &fakeQuant{})
	router := server.Router()

	for _, tc := range []struct {
		method string
		path   string
	}{
		{http.MethodGet, "/api/strategies"},
		{http.MethodGet, "/api/auth/me"},
		{http.MethodGet, "/api/users"},
		{http.MethodGet, "/api/backtests"},
	} {
		rec := doAuthRequest(router, tc.method, tc.path, "", nil)
		if rec.Code != http.StatusUnauthorized {
			t.Fatalf("%s %s status = %d", tc.method, tc.path, rec.Code)
		}
	}
}

func TestAuthLoginRejectsWrongPassword(t *testing.T) {
	db := newFakeDB()
	server := newAuthTestServer(t, db, &fakeQuant{})
	bootstrapAdmin(t, server)

	rec := doAuthRequest(server.Router(), http.MethodPost, "/api/auth/login",
		`{"email":"admin@example.com","password":"wrong-password"}`, nil)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestNonAdminCannotListUsers(t *testing.T) {
	db := newFakeDB()
	server := newAuthTestServer(t, db, &fakeQuant{})
	admin := bootstrapAdmin(t, server)

	created := doAuthRequest(server.Router(), http.MethodPost, "/api/users",
		`{"email":"user@example.com","password":"password123","role":"user"}`, admin)
	if created.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", created.Code, created.Body)
	}

	userCookie := login(t, server, "user@example.com", "password123")
	rec := doAuthRequest(server.Router(), http.MethodGet, "/api/users", "", userCookie)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestBacktestIsPartitionedPerUser(t *testing.T) {
	db := newFakeDB()
	fake := &fakeQuant{result: json.RawMessage(`{
		"strategy": "ma_cross",
		"final_equity": 10100,
		"metrics": {"total_return": 0.01},
		"report_dir": "/tmp/report"
	}`)}
	server := newAuthTestServer(t, db, fake)
	router := server.Router()
	admin := bootstrapAdmin(t, server)

	adminRun := doAuthRequest(router, http.MethodPost, "/api/backtests",
		`{"strategy":"ma_cross","symbols":["BTCUSDT"],"days":2}`, admin)
	if adminRun.Code != http.StatusOK {
		t.Fatalf("admin backtest status = %d body = %s", adminRun.Code, adminRun.Body)
	}
	if fake.got.ReportGroup != "user_1" {
		t.Fatalf("admin report group = %q", fake.got.ReportGroup)
	}

	created := doAuthRequest(router, http.MethodPost, "/api/users",
		`{"email":"user@example.com","password":"password123","role":"user"}`, admin)
	if created.Code != http.StatusCreated {
		t.Fatalf("create status = %d body = %s", created.Code, created.Body)
	}
	userCookie := login(t, server, "user@example.com", "password123")

	userRun := doAuthRequest(router, http.MethodPost, "/api/backtests",
		`{"strategy":"ma_cross","symbols":["ETHUSDT"],"days":2}`, userCookie)
	if userRun.Code != http.StatusOK {
		t.Fatalf("user backtest status = %d body = %s", userRun.Code, userRun.Body)
	}
	if fake.got.ReportGroup != "user_2" {
		t.Fatalf("user report group = %q", fake.got.ReportGroup)
	}

	history := doAuthRequest(router, http.MethodGet, "/api/backtests", "", userCookie)
	if history.Code != http.StatusOK {
		t.Fatalf("history status = %d", history.Code)
	}
	var runs []runSummaryDTO
	if err := json.Unmarshal(history.Body.Bytes(), &runs); err != nil {
		t.Fatal(err)
	}
	if len(runs) != 1 || runs[0].ID != 2 {
		t.Fatalf("user history = %+v", runs)
	}
	if string(runs[0].Symbols) != `["ETHUSDT"]` {
		t.Fatalf("symbols = %s", runs[0].Symbols)
	}

	// The admin's run must not be readable by the normal user.
	foreign := doAuthRequest(router, http.MethodGet, "/api/backtests/1", "", userCookie)
	if foreign.Code != http.StatusNotFound {
		t.Fatalf("foreign run status = %d", foreign.Code)
	}
	own := doAuthRequest(router, http.MethodGet, "/api/backtests/2", "", userCookie)
	if own.Code != http.StatusOK {
		t.Fatalf("own run status = %d body = %s", own.Code, own.Body)
	}
	var ownPayload struct {
		Metrics map[string]float64 `json:"metrics"`
	}
	if err := json.Unmarshal(own.Body.Bytes(), &ownPayload); err != nil {
		t.Fatal(err)
	}
	if ownPayload.Metrics["total_return"] != 0.01 {
		t.Fatalf("own run payload = %s", own.Body)
	}
}

func TestCredentialsAreEncryptedAndMasked(t *testing.T) {
	db := newFakeDB()
	server := newAuthTestServer(t, db, &fakeQuant{})
	admin := bootstrapAdmin(t, server)

	put := doAuthRequest(server.Router(), http.MethodPut, "/api/me/credentials",
		`{"api_key":"abcdefghijklmnopwxyz","secret":"super-secret-value","label":"testnet"}`, admin)
	if put.Code != http.StatusOK {
		t.Fatalf("put status = %d body = %s", put.Code, put.Body)
	}
	if !strings.Contains(put.Body.String(), `"api_key_hint":"abcd…wxyz"`) {
		t.Fatalf("body = %s", put.Body)
	}

	stored := db.creds[1]
	if stored.APIKeyCipher == "abcdefghijklmnopwxyz" || stored.SecretCipher == "super-secret-value" {
		t.Fatal("credentials were stored in plaintext")
	}

	get := doAuthRequest(server.Router(), http.MethodGet, "/api/me/credentials", "", admin)
	if get.Code != http.StatusOK || !strings.Contains(get.Body.String(), `"configured":true`) {
		t.Fatalf("get status = %d body = %s", get.Code, get.Body)
	}

	del := doAuthRequest(server.Router(), http.MethodDelete, "/api/me/credentials", "", admin)
	if del.Code != http.StatusNoContent {
		t.Fatalf("delete status = %d", del.Code)
	}
	get = doAuthRequest(server.Router(), http.MethodGet, "/api/me/credentials", "", admin)
	if !strings.Contains(get.Body.String(), `"configured":false`) {
		t.Fatalf("after delete = %s", get.Body)
	}
}

func TestUnknownOriginCannotMutate(t *testing.T) {
	db := newFakeDB()
	server := newAuthTestServer(t, db, &fakeQuant{})

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "/api/auth/login", strings.NewReader(`{}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Origin", "https://evil.example")
	server.Router().ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("status = %d", rec.Code)
	}
}
