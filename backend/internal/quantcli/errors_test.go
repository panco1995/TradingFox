package quantcli

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

// TestInvalidParamsAreReportedNotSwallowed drives the real Python CLI with a
// parameter combination the strategy rejects.
//
// This is the regression that started it: the CLI printed the validation error
// to stdout, stderr stayed empty, and the web UI showed "exit status 2" with no
// hint about which parameter was wrong.
func TestInvalidParamsAreReportedNotSwallowed(t *testing.T) {
	client, err := Default()
	if err != nil {
		t.Skipf("python not configured: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	_, err = client.Backtest(ctx, BacktestRequest{
		Strategy: "donchian",
		Symbols:  []string{"BTCUSDT"},
		Days:     days(30),
		// exit_window >= entry_window is rejected by the param model.
		Params: map[string]any{"entry_window": 20, "exit_window": 30},
	})

	var cliErr *Error
	if !errors.As(err, &cliErr) {
		t.Fatalf("expected a cli error, got %v", err)
	}
	if cliErr.ExitCode != 2 {
		t.Fatalf("exit code = %d, want 2", cliErr.ExitCode)
	}
	if strings.Contains(cliErr.Message, "exit status") {
		t.Fatalf("message fell back to the bare process status: %q", cliErr.Message)
	}
	if !strings.Contains(cliErr.Message, "退出周期") {
		t.Fatalf("message does not explain the bad parameter: %q", cliErr.Message)
	}
}

// TestMissingDataIsNotAProcessStatus checks the exit-code-1 path, which had the
// same empty-stderr problem via an uncaught traceback on stdout.
func TestMissingDataIsNotAProcessStatus(t *testing.T) {
	client, err := Default()
	if err != nil {
		t.Skipf("python not configured: %v", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	_, err = client.Backtest(ctx, BacktestRequest{
		Strategy: "donchian",
		Symbols:  []string{"NODATAUSDT"},
		Days:     days(30),
	})

	var cliErr *Error
	if !errors.As(err, &cliErr) {
		t.Fatalf("expected a cli error, got %v", err)
	}
	if cliErr.InvalidInput() {
		t.Fatalf("missing data is not bad input, exit code = %d", cliErr.ExitCode)
	}
	if !strings.Contains(cliErr.Message, "no stored bars for NODATAUSDT") {
		t.Fatalf("message = %q", cliErr.Message)
	}
	if strings.Contains(cliErr.Message, "Traceback") {
		t.Fatalf("a data gap must not look like a crash: %q", cliErr.Message)
	}
}
