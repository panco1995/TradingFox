// Package quantcli invokes the Python quant CLI as a child process.
//
// The long-term design is gRPC between Go and Python; that is not built yet.
// Until then the Go API shells out to `python -m quant.cli ... --json`, which
// keeps a single source of truth for strategy discovery, validation and
// backtesting. Arguments are passed as an argv slice (never through a shell),
// so user input cannot inject commands.
package quantcli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// Error is a failed CLI invocation. Message is safe to show to the user.
type Error struct {
	Message  string
	Stderr   string
	ExitCode int
}

func (e *Error) Error() string { return e.Message }

// InvalidInput reports whether the CLI rejected the request (exit code 2).
func (e *Error) InvalidInput() bool { return e.ExitCode == 2 }

type Client struct {
	Python  string // path to the venv interpreter
	WorkDir string // directory containing the `quant` package
	Timeout time.Duration
}

// BacktestRequest mirrors the JSON body accepted by POST /api/backtests.
type BacktestRequest struct {
	Strategy    string         `json:"strategy"`
	Symbols     []string       `json:"symbols"`
	Days        *int           `json:"days"`
	Start       string         `json:"start"`
	End         string         `json:"end"`
	Interval    string         `json:"interval"`
	InitialCash float64        `json:"initial_cash"`
	FeeRate     float64        `json:"fee_rate"`
	SlippageBps float64        `json:"slippage_bps"`
	Params      map[string]any `json:"params"`
}

var symbolPattern = regexp.MustCompile(`^[A-Z0-9]{5,20}$`)

// Validate rejects obviously wrong input before spawning Python. Anything
// semantic (unknown strategy, parameter ranges) is left to the Python side,
// which owns the strategy schemas.
func (r *BacktestRequest) Validate() error {
	if strings.TrimSpace(r.Strategy) == "" {
		return errors.New("strategy is required")
	}
	if len(r.Symbols) == 0 {
		return errors.New("at least one symbol is required")
	}
	if len(r.Symbols) > 10 {
		return errors.New("at most 10 symbols per backtest")
	}
	for _, symbol := range r.Symbols {
		if !symbolPattern.MatchString(symbol) {
			return fmt.Errorf("invalid symbol %q (expected e.g. BTCUSDT)", symbol)
		}
	}
	if r.Start == "" {
		if r.Days == nil {
			days := 30
			r.Days = &days
		}
		if *r.Days < 1 || *r.Days > 3650 {
			return errors.New("days must be between 1 and 3650")
		}
	}
	if r.InitialCash < 0 {
		return errors.New("initial_cash must be positive")
	}
	if r.InitialCash == 0 {
		r.InitialCash = 10000
	}
	if r.FeeRate < 0 || r.FeeRate > 0.01 {
		return errors.New("fee_rate must be between 0 and 0.01")
	}
	if r.SlippageBps < 0 || r.SlippageBps > 100 {
		return errors.New("slippage_bps must be between 0 and 100")
	}
	if r.Interval == "" {
		r.Interval = "1m"
	}
	return nil
}

func (c *Client) baseArgs() []string { return []string{"-m", "quant.cli"} }

func (c *Client) run(ctx context.Context, args ...string) ([]byte, error) {
	if c == nil || c.Python == "" {
		return nil, errors.New("quant python interpreter is not configured")
	}

	timeout := c.Timeout
	if timeout <= 0 {
		timeout = 5 * time.Minute
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, c.Python, append(c.baseArgs(), args...)...)
	cmd.Dir = c.WorkDir

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	if ctx.Err() == context.DeadlineExceeded {
		return nil, &Error{Message: "回测超时，请缩小时间范围或标的数量", ExitCode: -1}
	}
	if err != nil {
		var exitErr *exec.ExitError
		code := -1
		if errors.As(err, &exitErr) {
			code = exitErr.ExitCode()
		}
		message := strings.TrimSpace(stderr.String())
		if message == "" {
			message = err.Error()
		}
		return nil, &Error{Message: message, Stderr: stderr.String(), ExitCode: code}
	}
	return stdout.Bytes(), nil
}

// Strategies returns the raw JSON array emitted by `quant strategies --json`.
func (c *Client) Strategies(ctx context.Context) (json.RawMessage, error) {
	out, err := c.run(ctx, "strategies", "--json")
	if err != nil {
		return nil, err
	}
	if !json.Valid(out) {
		return nil, errors.New("python CLI returned malformed JSON for strategies")
	}
	return json.RawMessage(out), nil
}

// Backtest runs a backtest and returns its JSON report.
func (c *Client) Backtest(ctx context.Context, req BacktestRequest) (json.RawMessage, error) {
	if err := req.Validate(); err != nil {
		return nil, &Error{Message: err.Error(), ExitCode: 2}
	}

	args := []string{"backtest", "--strategy", req.Strategy, "--interval", req.Interval}
	for _, symbol := range req.Symbols {
		args = append(args, "--symbol", symbol)
	}
	if req.Start != "" {
		args = append(args, "--start", req.Start)
	} else if req.Days != nil {
		args = append(args, "--days", strconv.Itoa(*req.Days))
	}
	if req.End != "" {
		args = append(args, "--end", req.End)
	}
	args = append(
		args,
		"--cash", strconv.FormatFloat(req.InitialCash, 'f', -1, 64),
		"--fee-rate", strconv.FormatFloat(req.FeeRate, 'f', -1, 64),
		"--slippage-bps", strconv.FormatFloat(req.SlippageBps, 'f', -1, 64),
	)
	for key, value := range req.Params {
		args = append(args, "--param", key+"="+scalarString(value))
	}
	args = append(args, "--json")

	out, err := c.run(ctx, args...)
	if err != nil {
		return nil, err
	}
	if !json.Valid(out) {
		return nil, errors.New("python CLI returned malformed JSON for backtest")
	}
	return json.RawMessage(out), nil
}

func scalarString(value any) string {
	switch v := value.(type) {
	case string:
		return v
	case json.Number:
		return v.String()
	case float64:
		return strconv.FormatFloat(v, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(v)
	case nil:
		return ""
	default:
		return fmt.Sprint(v)
	}
}

// Default locates the repository, the Python venv and the data directory.
func Default() (*Client, error) {
	root, err := findRoot()
	if err != nil {
		return nil, err
	}
	python := os.Getenv("QUANT_PYTHON")
	if python == "" {
		python = filepath.Join(root, "quant", ".venv", "bin", "python")
	}
	if _, err := os.Stat(python); err != nil {
		return nil, fmt.Errorf("python interpreter not found at %s (run `make install` or set QUANT_PYTHON)", python)
	}
	return &Client{
		Python:  python,
		WorkDir: filepath.Join(root, "quant"),
		Timeout: 5 * time.Minute,
	}, nil
}

// findRoot walks upwards looking for the quant package marker.
func findRoot() (string, error) {
	if root := os.Getenv("QUANT_ROOT"); root != "" {
		return filepath.Abs(root)
	}
	dir, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for range 8 {
		if _, err := os.Stat(filepath.Join(dir, "quant", "pyproject.toml")); err == nil {
			return dir, nil
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "", errors.New("cannot locate repository root (set QUANT_ROOT)")
}
