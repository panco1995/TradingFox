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
	"time"

	"github.com/gin-gonic/gin"

	"github.com/tm00013/trading/backend/internal/quantcli"
)

type fakeQuant struct {
	strategies     json.RawMessage
	result         json.RawMessage
	klines         json.RawMessage
	symbols        json.RawMessage
	status         json.RawMessage
	symbolsResult  json.RawMessage
	backfillPlan   json.RawMessage
	backfillResult json.RawMessage
	// backfillGate, when set, blocks Backfill until the test closes it. That is
	// what makes "a second job is rejected while one runs" deterministic.
	backfillGate chan struct{}
	err          error
	got          quantcli.BacktestRequest
	gotKline     quantcli.KlineQuery
	gotInterval  string
	gotAction    string
	gotSymbol    string
	gotUpdatedBy string
}

func (f *fakeQuant) Strategies(context.Context) (json.RawMessage, error) {
	return f.strategies, f.err
}

func (f *fakeQuant) Backtest(_ context.Context, req quantcli.BacktestRequest) (json.RawMessage, error) {
	f.got = req
	return f.result, f.err
}

func (f *fakeQuant) Klines(_ context.Context, query quantcli.KlineQuery) (json.RawMessage, error) {
	f.gotKline = query
	if f.klines != nil {
		return f.klines, f.err
	}
	return f.result, f.err
}

func (f *fakeQuant) KlineSymbols(_ context.Context, interval string) (json.RawMessage, error) {
	f.gotInterval = interval
	if f.symbols != nil {
		return f.symbols, f.err
	}
	return json.RawMessage(`{"interval":"` + interval + `","symbols":[]}`), f.err
}

func (f *fakeQuant) CollectorStatus(_ context.Context, interval string) (json.RawMessage, error) {
	f.gotInterval = interval
	if f.status != nil {
		return f.status, f.err
	}
	return json.RawMessage(`{"collector":{"running":false},"symbols":[]}`), f.err
}

func (f *fakeQuant) Symbols(
	_ context.Context, action, symbol, updatedBy string,
) (json.RawMessage, error) {
	f.gotAction = action
	f.gotSymbol = symbol
	f.gotUpdatedBy = updatedBy
	if f.symbolsResult != nil {
		return f.symbolsResult, f.err
	}
	return json.RawMessage(`{"symbols":["BTCUSDT"],"message":""}`), f.err
}

func (f *fakeQuant) BackfillPlan(
	_ context.Context, symbol string, days int, interval string,
) (json.RawMessage, error) {
	f.gotSymbol = symbol
	if f.backfillPlan != nil {
		return f.backfillPlan, f.err
	}
	return json.RawMessage(`{"symbol":"BTCUSDT","complete":true,"spans":[]}`), f.err
}

func (f *fakeQuant) Backfill(
	_ context.Context, symbol string, days int, interval string, force bool,
) (json.RawMessage, error) {
	f.gotSymbol = symbol
	if f.backfillGate != nil {
		<-f.backfillGate
	}
	if f.backfillResult != nil {
		return f.backfillResult, f.err
	}
	return json.RawMessage(`{"symbol":"BTCUSDT","skipped":true}`), f.err
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

func TestKlinesPassThrough(t *testing.T) {
	fake := &fakeQuant{klines: json.RawMessage(`{"symbol":"BTCUSDT","count":0,"bars":[]}`)}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/klines?symbol=btcusdt&interval=1h&days=3", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotKline.Symbol != "BTCUSDT" || fake.gotKline.Interval != "1h" || fake.gotKline.Days != 3 {
		t.Fatalf("query = %+v", fake.gotKline)
	}
	if fake.gotKline.Limit != 10_000 {
		t.Fatalf("limit = %d", fake.gotKline.Limit)
	}
	if got := strings.TrimSpace(rec.Body.String()); got != `{"symbol":"BTCUSDT","count":0,"bars":[]}` {
		t.Fatalf("body = %s", got)
	}
}

func TestKlinesRejectsBadSymbol(t *testing.T) {
	fake := &fakeQuant{}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/klines?symbol=BTC&days=2", "")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotKline.Symbol != "" {
		t.Fatalf("python was called: %+v", fake.gotKline)
	}
}

func TestKlineSymbolsPassThrough(t *testing.T) {
	fake := &fakeQuant{symbols: json.RawMessage(`{"interval":"1m","symbols":["BTCUSDT"]}`)}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/klines/symbols?interval=1m", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotInterval != "1m" {
		t.Fatalf("interval = %s", fake.gotInterval)
	}
}

func TestCollectorStatusPassThrough(t *testing.T) {
	fake := &fakeQuant{status: json.RawMessage(`{"collector":{"running":true},"symbols":[]}`)}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/collector?interval=1m", "")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotInterval != "1m" {
		t.Fatalf("interval = %s", fake.gotInterval)
	}
	if got := strings.TrimSpace(rec.Body.String()); !strings.Contains(got, `"running":true`) {
		t.Fatalf("body = %s", got)
	}
}

func TestCollectorStatusRejectsBadInterval(t *testing.T) {
	fake := &fakeQuant{}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/collector?interval=2x", "")
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
}

func TestAddSymbolValidatesAndPassesUser(t *testing.T) {
	fake := &fakeQuant{
		symbolsResult: json.RawMessage(`{"symbols":["BTCUSDT","SOLUSDT"],"message":"SOLUSDT 已加入"}`),
	}
	rec := doRequest(
		newTestServer(fake).Router(), http.MethodPost, "/api/symbols", `{"symbol":"solusdt"}`,
	)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotAction != "add" || fake.gotSymbol != "SOLUSDT" {
		t.Fatalf("action=%s symbol=%s", fake.gotAction, fake.gotSymbol)
	}
	if fake.gotUpdatedBy != "user_1" {
		t.Fatalf("updatedBy = %s", fake.gotUpdatedBy)
	}
}

func TestAddSymbolRejectsEmptyBody(t *testing.T) {
	fake := &fakeQuant{}
	rec := doRequest(newTestServer(fake).Router(), http.MethodPost, "/api/symbols", `{"symbol":"  "}`)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	// Nothing may reach Python when the request itself is empty.
	if fake.gotAction != "" {
		t.Fatalf("python was called: %s", fake.gotAction)
	}
}

func TestAddSymbolSurfacesCliRejection(t *testing.T) {
	fake := &fakeQuant{
		err: &quantcli.Error{Message: "交易所没有 FOOBARUSDT 这个交易对", ExitCode: 2},
	}
	rec := doRequest(
		newTestServer(fake).Router(), http.MethodPost, "/api/symbols", `{"symbol":"FOOBARUSDT"}`,
	)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if !strings.Contains(rec.Body.String(), "交易所没有") {
		t.Fatalf("body = %s", rec.Body)
	}
}

func TestRemoveSymbol(t *testing.T) {
	fake := &fakeQuant{symbolsResult: json.RawMessage(`{"symbols":["BTCUSDT"]}`)}
	rec := doRequest(newTestServer(fake).Router(), http.MethodDelete, "/api/symbols/ethusdt", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotAction != "remove" || fake.gotSymbol != "ETHUSDT" {
		t.Fatalf("action=%s symbol=%s", fake.gotAction, fake.gotSymbol)
	}
}

func TestListSymbols(t *testing.T) {
	fake := &fakeQuant{symbolsResult: json.RawMessage(`{"symbols":["BTCUSDT","ETHUSDT"]}`)}
	rec := doRequest(newTestServer(fake).Router(), http.MethodGet, "/api/symbols", "")

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotAction != "list" {
		t.Fatalf("action = %s", fake.gotAction)
	}
}

func TestBackfillPlanPassThrough(t *testing.T) {
	fake := &fakeQuant{
		backfillPlan: json.RawMessage(`{"symbol":"SOLUSDT","complete":false,"missing_bars":100}`),
	}
	rec := doRequest(
		newTestServer(fake).Router(), http.MethodGet, "/api/backfill/plan?symbol=solusdt&days=365", "",
	)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotSymbol != "SOLUSDT" {
		t.Fatalf("symbol = %s", fake.gotSymbol)
	}
	if !strings.Contains(rec.Body.String(), "missing_bars") {
		t.Fatalf("body = %s", rec.Body)
	}
}

func TestStartBackfillReturnsImmediately(t *testing.T) {
	fake := &fakeQuant{backfillResult: json.RawMessage(`{"symbol":"SOLUSDT","skipped":true}`)}
	server := newTestServer(fake)

	rec := doRequest(server.Router(), http.MethodPost, "/api/backfill", `{"symbol":"SOLUSDT","days":365}`)
	if rec.Code != http.StatusAccepted {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}

	// The job must appear right away, even before Python finishes.
	var job backfillJob
	if err := json.Unmarshal(rec.Body.Bytes(), &job); err != nil {
		t.Fatal(err)
	}
	if job.Symbol != "SOLUSDT" {
		t.Fatalf("job = %+v", job)
	}

	waitForBackfill(t, server, "SOLUSDT", "done")
}

func TestSecondBackfillForSameSymbolIsRejected(t *testing.T) {
	gate := make(chan struct{})
	fake := &fakeQuant{
		backfillResult: json.RawMessage(`{"symbol":"SOLUSDT"}`),
		backfillGate:   gate,
	}
	server := newTestServer(fake)
	router := server.Router()

	first := doRequest(router, http.MethodPost, "/api/backfill", `{"symbol":"SOLUSDT"}`)
	if first.Code != http.StatusAccepted {
		t.Fatalf("first status = %d", first.Code)
	}
	second := doRequest(router, http.MethodPost, "/api/backfill", `{"symbol":"SOLUSDT"}`)
	if second.Code != http.StatusConflict {
		t.Fatalf("second status = %d body = %s", second.Code, second.Body)
	}

	close(gate)
	waitForBackfill(t, server, "SOLUSDT", "done")

	// Once finished, the symbol can be backfilled again.
	third := doRequest(router, http.MethodPost, "/api/backfill", `{"symbol":"SOLUSDT"}`)
	if third.Code != http.StatusAccepted {
		t.Fatalf("third status = %d body = %s", third.Code, third.Body)
	}
	waitForBackfill(t, server, "SOLUSDT", "done")
}

func TestBackfillRejectsEmptySymbol(t *testing.T) {
	fake := &fakeQuant{}
	rec := doRequest(newTestServer(fake).Router(), http.MethodPost, "/api/backfill", `{"symbol":""}`)
	if rec.Code != http.StatusBadRequest {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
	if fake.gotSymbol != "" {
		t.Fatalf("python was called for %q", fake.gotSymbol)
	}
}

func TestBackfillStatusUnknownSymbol(t *testing.T) {
	rec := doRequest(newTestServer(&fakeQuant{}).Router(), http.MethodGet, "/api/backfill/NOPEUSDT", "")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d body = %s", rec.Code, rec.Body)
	}
}

// waitForBackfill polls the registry until the job leaves the running states,
// so tests do not leak a goroutine into the next case.
func waitForBackfill(t *testing.T, server *Server, symbol, want string) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		job, ok := server.backfills.get(symbol)
		if ok && job.State == want {
			return
		}
		time.Sleep(5 * time.Millisecond)
	}
	job, _ := server.backfills.get(symbol)
	t.Fatalf("backfill state = %q, want %q", job.State, want)
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
