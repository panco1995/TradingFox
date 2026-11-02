// Package store owns all MySQL access for the API.
//
// The schema is deliberately small for V1: users, their encrypted exchange
// credentials and a history of backtest runs. Market data never lives here.
package store

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net"
	"os"
	"time"

	"github.com/go-sql-driver/mysql"
)

var (
	ErrNotFound   = errors.New("record not found")
	ErrEmailTaken = errors.New("email already registered")
)

// User is an admin-console account. PasswordHash is never serialised.
type User struct {
	ID           int64
	Email        string
	PasswordHash string
	Role         string // admin | user
	Status       string // active | disabled
	CreatedAt    time.Time
}

// Credentials is an encrypted exchange API key pair.
type Credentials struct {
	UserID       int64
	Exchange     string
	Label        string
	APIKeyCipher string
	SecretCipher string
	APIKeyHint   string
	UpdatedAt    time.Time
}

// Run is one persisted backtest.
type Run struct {
	ID          int64
	UserID      int64
	Strategy    string
	Symbols     string // JSON array
	Params      string // JSON object
	ReportDir   string
	TotalReturn *float64
	FinalEquity *float64
	ResultJSON  string
	CreatedAt   time.Time
}

// RunSummary is the lightweight row used by the history list.
type RunSummary struct {
	ID          int64
	Strategy    string
	Symbols     string
	ReportDir   string
	TotalReturn *float64
	FinalEquity *float64
	CreatedAt   time.Time
}

// DB wraps a *sql.DB with the queries the API needs.
type DB struct {
	sql *sql.DB
}

// OpenFromEnv connects using MYSQL_DSN or the individual MYSQL_* variables.
func OpenFromEnv() (*DB, error) {
	dsn := os.Getenv("MYSQL_DSN")
	if dsn == "" {
		cfg := mysql.NewConfig()
		cfg.User = envOr("MYSQL_USER", "trader")
		cfg.Passwd = envOr("MYSQL_PASSWORD", "trader")
		cfg.Net = "tcp"
		cfg.Addr = net.JoinHostPort(envOr("MYSQL_HOST", "127.0.0.1"), envOr("MYSQL_PORT", "3306"))
		cfg.DBName = envOr("MYSQL_DATABASE", "trading")
		cfg.ParseTime = true
		cfg.Loc = time.UTC
		cfg.Collation = "utf8mb4_0900_ai_ci"
		cfg.Timeout = 5 * time.Second
		cfg.ReadTimeout = 30 * time.Second
		cfg.WriteTimeout = 30 * time.Second
		dsn = cfg.FormatDSN()
	}
	return Open(dsn)
}

func Open(dsn string) (*DB, error) {
	sqlDB, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, fmt.Errorf("open mysql: %w", err)
	}
	sqlDB.SetMaxOpenConns(10)
	sqlDB.SetMaxIdleConns(5)
	sqlDB.SetConnMaxLifetime(30 * time.Minute)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := sqlDB.PingContext(ctx); err != nil {
		sqlDB.Close()
		return nil, fmt.Errorf("ping mysql: %w", err)
	}
	return &DB{sql: sqlDB}, nil
}

func (d *DB) Close() error { return d.sql.Close() }

// Migrate applies the idempotent schema. It is safe to run on every boot.
func (d *DB) Migrate(ctx context.Context) error {
	for _, stmt := range schema {
		if _, err := d.sql.ExecContext(ctx, stmt); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
	}
	return nil
}

// ------------------------------------------------------------------- users

func (d *DB) CountUsers(ctx context.Context) (int64, error) {
	var count int64
	err := d.sql.QueryRowContext(ctx, `SELECT COUNT(*) FROM users`).Scan(&count)
	return count, err
}

func (d *DB) CreateUser(ctx context.Context, email, passwordHash, role string) (User, error) {
	res, err := d.sql.ExecContext(ctx,
		`INSERT INTO users (email, password_hash, role) VALUES (?, ?, ?)`,
		email, passwordHash, role,
	)
	if err != nil {
		var mysqlErr *mysql.MySQLError
		if errors.As(err, &mysqlErr) && mysqlErr.Number == 1062 {
			return User{}, ErrEmailTaken
		}
		return User{}, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return User{}, err
	}
	return d.UserByID(ctx, id)
}

func (d *DB) UserByEmail(ctx context.Context, email string) (User, error) {
	return scanUser(d.sql.QueryRowContext(ctx,
		`SELECT id, email, password_hash, role, status, created_at FROM users WHERE email = ?`,
		email,
	))
}

func (d *DB) UserByID(ctx context.Context, id int64) (User, error) {
	return scanUser(d.sql.QueryRowContext(ctx,
		`SELECT id, email, password_hash, role, status, created_at FROM users WHERE id = ?`,
		id,
	))
}

func (d *DB) ListUsers(ctx context.Context) ([]User, error) {
	rows, err := d.sql.QueryContext(ctx,
		`SELECT id, email, password_hash, role, status, created_at FROM users ORDER BY id`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var users []User
	for rows.Next() {
		var user User
		if err := rows.Scan(&user.ID, &user.Email, &user.PasswordHash, &user.Role, &user.Status, &user.CreatedAt); err != nil {
			return nil, err
		}
		users = append(users, user)
	}
	return users, rows.Err()
}

func scanUser(row *sql.Row) (User, error) {
	var user User
	err := row.Scan(&user.ID, &user.Email, &user.PasswordHash, &user.Role, &user.Status, &user.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return User{}, ErrNotFound
	}
	return user, err
}

// ------------------------------------------------------------- credentials

func (d *DB) UpsertCredentials(ctx context.Context, userID int64, exchange, label, apiKeyCipher, secretCipher, hint string) error {
	_, err := d.sql.ExecContext(ctx, `
		INSERT INTO exchange_credentials
			(user_id, exchange, label, api_key_cipher, secret_cipher, api_key_hint)
		VALUES (?, ?, ?, ?, ?, ?) AS new
		ON DUPLICATE KEY UPDATE
			label = new.label,
			api_key_cipher = new.api_key_cipher,
			secret_cipher = new.secret_cipher,
			api_key_hint = new.api_key_hint`,
		userID, exchange, label, apiKeyCipher, secretCipher, hint,
	)
	return err
}

func (d *DB) GetCredentials(ctx context.Context, userID int64, exchange string) (Credentials, error) {
	var c Credentials
	err := d.sql.QueryRowContext(ctx, `
		SELECT user_id, exchange, label, api_key_cipher, secret_cipher, api_key_hint, updated_at
		FROM exchange_credentials WHERE user_id = ? AND exchange = ?`,
		userID, exchange,
	).Scan(&c.UserID, &c.Exchange, &c.Label, &c.APIKeyCipher, &c.SecretCipher, &c.APIKeyHint, &c.UpdatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return Credentials{}, ErrNotFound
	}
	return c, err
}

func (d *DB) DeleteCredentials(ctx context.Context, userID int64, exchange string) error {
	_, err := d.sql.ExecContext(ctx,
		`DELETE FROM exchange_credentials WHERE user_id = ? AND exchange = ?`,
		userID, exchange,
	)
	return err
}

// ------------------------------------------------------------------- runs

func (d *DB) RecordRun(ctx context.Context, run Run) (int64, error) {
	res, err := d.sql.ExecContext(ctx, `
		INSERT INTO backtest_runs
			(user_id, strategy, symbols, params, report_dir, total_return, final_equity, result_json)
		VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
		run.UserID, run.Strategy, run.Symbols, run.Params, nullable(run.ReportDir),
		run.TotalReturn, run.FinalEquity, run.ResultJSON,
	)
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

func (d *DB) ListRuns(ctx context.Context, userID int64, limit int) ([]RunSummary, error) {
	rows, err := d.sql.QueryContext(ctx, `
		SELECT id, strategy, symbols, report_dir, total_return, final_equity, created_at
		FROM backtest_runs WHERE user_id = ? ORDER BY id DESC LIMIT ?`,
		userID, limit,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var runs []RunSummary
	for rows.Next() {
		var (
			run    RunSummary
			report sql.NullString
			total  sql.NullFloat64
			equity sql.NullFloat64
		)
		if err := rows.Scan(&run.ID, &run.Strategy, &run.Symbols, &report, &total, &equity, &run.CreatedAt); err != nil {
			return nil, err
		}
		run.ReportDir = report.String
		if total.Valid {
			run.TotalReturn = &total.Float64
		}
		if equity.Valid {
			run.FinalEquity = &equity.Float64
		}
		runs = append(runs, run)
	}
	return runs, rows.Err()
}

func (d *DB) GetRun(ctx context.Context, userID, id int64) (Run, error) {
	var (
		run    Run
		report sql.NullString
		total  sql.NullFloat64
		equity sql.NullFloat64
	)
	err := d.sql.QueryRowContext(ctx, `
		SELECT id, user_id, strategy, symbols, params, report_dir,
		       total_return, final_equity, result_json, created_at
		FROM backtest_runs WHERE id = ? AND user_id = ?`,
		id, userID,
	).Scan(&run.ID, &run.UserID, &run.Strategy, &run.Symbols, &run.Params, &report,
		&total, &equity, &run.ResultJSON, &run.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return Run{}, ErrNotFound
	}
	run.ReportDir = report.String
	if total.Valid {
		run.TotalReturn = &total.Float64
	}
	if equity.Valid {
		run.FinalEquity = &equity.Float64
	}
	return run, err
}

func nullable(value string) any {
	if value == "" {
		return nil
	}
	return value
}

func envOr(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
