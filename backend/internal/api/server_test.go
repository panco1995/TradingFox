package api

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/quantcli"
)

type fakeQuant struct {
	strategies json.RawMessage
	result     json.RawMessage
	err        error
	got        quantcli.BacktestRequest
}

func (f *fakeQuant) Strategies(context.Context) (json.RawMessage, error) {
	return f.strategies, f.err
}

func (f *fakeQuant) Backtest(_ context.Context, req quantcli.BacktestRequest) (json.RawMessage, error) {
	f.got = req
	return f.result, f.err
}

func init() {
	gin.SetMode(gin.TestMode)
}

func newTestServer(quant Quant) *Server {
	return New(quant, slog.New(slog.NewTextHandler(io.Discard, nil)), Config{
		AllowedOrigins: []string{"http://localhost:5173"},
	})
}

func doRequest(handler http.Handler, method, path, body string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	req.Header.Set("Content-Type", "application/json")
	handler.ServeHTTP(rec, req)
	return rec
}

func TestHealth(t *testing.T) {
	rec := doRequest(newTestServer(&fakeQuant{}).Router(), http.MethodGet, "/api/health", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d", rec.Code)
	}
	var payload map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload["status"] != "ok" {
		t.Fatalf("payload = %v", payload)
	}
}

func TestStrategiesPassThrough(t *testing.T) {
	fake := &fakeQuant{strategies: json.RawMessage(`[{"name":"ma_cross"}]`)}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/strategies", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if got := strings.TrimSpace(rec.Body.String()); got != `[{"name":"ma_cross"}]` {
		t.Fatalf("body = %s", got)
	}
}

func TestBacktestDecodesParams(t *testing.T) {
	fake := &fakeQuant{result: json.RawMessage(`{"strategy":"ma_cross","metrics":{}}`)}
	body := `{
		"strategy": "ma_cross",
		"symbols": ["BTCUSDT"],
		"days": 7,
		"initial_cash": 5000,
		"fee_rate": 0.0005,
		"slippage_bps": 2,
		"params": {"fast": 10, "slow": 30, "target": 0.5, "flag": true}
	}`
	rec := doRequest(newTestServer(fake).Router(), http.MethodPost, "/api/backtests", body)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.got.Strategy != "ma_cross" || len(fake.got.Symbols) != 1 {
		t.Fatalf("request not forwarded: %+v", fake.got)
	}
	if *fake.got.Days != 7 {
		t.Fatalf("days = %v", *fake.got.Days)
	}
	// numbers stay json.Number so "10" does not become "10.000000"
	if got := fake.got.Params["fast"].(json.Number).String(); got != "10" {
		t.Fatalf("fast = %q", got)
	}
}

func TestBacktestRejectsUnknownField(t *testing.T) {
	rec := doRequest(newTestServer(&fakeQuant{}).Router(), http.MethodPost, "/api/backtests",
		`{"strategy":"ma_cross","symbols":["BTCUSDT"],"bonus":1}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestBacktestRejectsMalformedJSON(t *testing.T) {
	rec := doRequest(newTestServer(&fakeQuant{}).Router(), http.MethodPost, "/api/backtests", `{`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestBacktestMapsCLIValidationErrorTo400(t *testing.T) {
	fake := &fakeQuant{err: &quantcli.Error{Message: "fast must be smaller than slow", ExitCode: 2}}
	rec := doRequest(newTestServer(fake).Router(), http.MethodPost, "/api/backtests",
		`{"strategy":"ma_cross","symbols":["BTCUSDT"]}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "fast must be smaller than slow") {
		t.Fatalf("body = %s", rec.Body)
	}
}

func TestBacktestMapsCLIInternalErrorTo502(t *testing.T) {
	fake := &fakeQuant{err: &quantcli.Error{Message: "boom", ExitCode: 1}}
	rec := doRequest(newTestServer(fake).Router(), http.MethodPost, "/api/backtests",
		`{"strategy":"ma_cross","symbols":["BTCUSDT"]}`)

	if rec.Code != http.StatusBadGateway {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestBacktestIsSingleFlight(t *testing.T) {
	server := newTestServer(&fakeQuant{})
	server.sems[1] = make(chan struct{}, 1)
	server.sems[1] <- struct{}{} // simulate a running backtest for the test user
	defer func() { <-server.sems[1] }()

	rec := doRequest(server.Router(), http.MethodPost, "/api/backtests",
		`{"strategy":"ma_cross","symbols":["BTCUSDT"]}`)

	if rec.Code != http.StatusConflict {
		t.Fatalf("status = %d", rec.Code)
	}
}

func TestCORSAllowsConfiguredOrigin(t *testing.T) {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodOptions, "/api/backtests", nil)
	req.Header.Set("Origin", "http://localhost:5173")
	req.Header.Set("Access-Control-Request-Method", "POST")
	newTestServer(&fakeQuant{}).Router().ServeHTTP(rec, req)

	if rec.Code != http.StatusNoContent {
		t.Fatalf("status = %d", rec.Code)
	}
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "http://localhost:5173" {
		t.Fatalf("allow-origin = %q", got)
	}
}

func TestCORSAllowsSameHostWithoutConfig(t *testing.T) {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodPost, "http://trading.example.com/api/auth/login", nil)
	req.Header.Set("Origin", "https://trading.example.com")
	req.Header.Set("Content-Type", "application/json")
	newTestServer(&fakeQuant{}).Router().ServeHTTP(rec, req)

	if rec.Code == http.StatusForbidden {
		t.Fatalf("same-host origin was rejected: %d", rec.Code)
	}
	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "https://trading.example.com" {
		t.Fatalf("allow-origin = %q", got)
	}
}

func TestCORSRejectsUnknownOrigin(t *testing.T) {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/health", nil)
	req.Header.Set("Origin", "https://evil.example")
	newTestServer(&fakeQuant{}).Router().ServeHTTP(rec, req)

	if got := rec.Header().Get("Access-Control-Allow-Origin"); got != "" {
		t.Fatalf("allow-origin = %q, want empty", got)
	}
}

func TestUnknownRouteReturnsJSON(t *testing.T) {
	rec := doRequest(newTestServer(&fakeQuant{}).Router(), http.MethodGet, "/nope", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d", rec.Code)
	}
	if !strings.Contains(rec.Body.String(), "not found") {
		t.Fatalf("body = %s", rec.Body)
	}
}
