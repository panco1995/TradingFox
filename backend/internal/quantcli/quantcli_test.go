package quantcli

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func days(n int) *int { return &n }

func TestValidateDefaults(t *testing.T) {
	req := BacktestRequest{
		Strategy: "ma_cross",
		Symbols:  []string{"BTCUSDT"},
	}

	if err := req.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if req.Days == nil || *req.Days != 30 {
		t.Fatalf("expected default days=30, got %v", req.Days)
	}
	if req.Interval != "1m" {
		t.Fatalf("expected default interval=1m, got %q", req.Interval)
	}
	if req.InitialCash != 10000 {
		t.Fatalf("expected default cash=10000, got %v", req.InitialCash)
	}
}

func TestValidateRejections(t *testing.T) {
	cases := []struct {
		name string
		req  BacktestRequest
		want string
	}{
		{"no strategy", BacktestRequest{Symbols: []string{"BTCUSDT"}}, "strategy"},
		{"no symbols", BacktestRequest{Strategy: "ma_cross"}, "symbol"},
		{"bad symbol", BacktestRequest{Strategy: "ma_cross", Symbols: []string{"btc-usdt"}}, "invalid symbol"},
		{"too many symbols", BacktestRequest{
			Strategy: "ma_cross",
			Symbols:  []string{"SYM001", "SYM002", "SYM003", "SYM004", "SYM005", "SYM006", "SYM007", "SYM008", "SYM009", "SYM010", "SYM011"},
		}, "at most 10"},
		{"days zero", BacktestRequest{Strategy: "ma_cross", Symbols: []string{"BTCUSDT"}, Days: days(0)}, "days"},
		{"negative fee", BacktestRequest{Strategy: "ma_cross", Symbols: []string{"BTCUSDT"}, FeeRate: -1}, "fee_rate"},
		{"large slippage", BacktestRequest{Strategy: "ma_cross", Symbols: []string{"BTCUSDT"}, SlippageBps: 500}, "slippage_bps"},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := tc.req.Validate()
			if err == nil {
				t.Fatal("expected an error")
			}
			if !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("error %q does not mention %q", err, tc.want)
			}
		})
	}
}

func TestValidateSkipsDaysWhenStartGiven(t *testing.T) {
	req := BacktestRequest{
		Strategy: "donchian",
		Symbols:  []string{"BTCUSDT", "ETHUSDT"},
		Start:    "2026-01-01",
	}

	if err := req.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if req.Days != nil {
		t.Fatalf("days should stay nil when start is set, got %v", req.Days)
	}
}

func TestScalarString(t *testing.T) {
	cases := map[string]any{
		"3":       json.Number("3"),
		"2.5":     json.Number("2.5"),
		"true":    true,
		"0.95":    0.95,
		"BTCUSDT": "BTCUSDT",
	}
	for want, input := range cases {
		if got := scalarString(input); got != want {
			t.Fatalf("scalarString(%v) = %q, want %q", input, got, want)
		}
	}
}

// A python crash writes to stderr; that text is what the UI shows.
func TestFailureMessagePrefersStderr(t *testing.T) {
	var stdout, stderr bytes.Buffer
	stdout.WriteString(`{"error": "from stdout"}`)
	stderr.WriteString("参数不合法：快线周期必须小于慢线周期\n")

	got := failureMessage(&stdout, &stderr, errors.New("exit status 2"))

	if got != "参数不合法：快线周期必须小于慢线周期" {
		t.Fatalf("got %q", got)
	}
}

// Without the stdout fallback the user would only see "exit status 2", which
// says nothing about which parameter is wrong.
func TestFailureMessageFallsBackToJSONEnvelope(t *testing.T) {
	var stdout, stderr bytes.Buffer
	stdout.WriteString(`{"error": "参数不合法：退出周期必须小于突破周期"}`)

	got := failureMessage(&stdout, &stderr, errors.New("exit status 2"))

	if got != "参数不合法：退出周期必须小于突破周期" {
		t.Fatalf("got %q", got)
	}
}

// Anything is better than an empty message in the error banner.
func TestFailureMessageLastResortIsTheRawError(t *testing.T) {
	var stdout, stderr bytes.Buffer
	stdout.WriteString("not json")

	got := failureMessage(&stdout, &stderr, errors.New("exit status 2"))

	if got != "exit status 2" {
		t.Fatalf("got %q", got)
	}
}
