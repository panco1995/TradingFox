package store

// schema is applied on every boot. Every statement is idempotent.
var schema = []string{
	`CREATE TABLE IF NOT EXISTS users (
		id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
		email VARCHAR(255) NOT NULL,
		password_hash VARCHAR(100) NOT NULL,
		role VARCHAR(16) NOT NULL DEFAULT 'user',
		status VARCHAR(16) NOT NULL DEFAULT 'active',
		created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
		updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
		PRIMARY KEY (id),
		UNIQUE KEY uk_users_email (email)
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci`,

	`CREATE TABLE IF NOT EXISTS exchange_credentials (
		user_id BIGINT UNSIGNED NOT NULL,
		exchange VARCHAR(16) NOT NULL,
		label VARCHAR(64) NOT NULL DEFAULT '',
		api_key_cipher TEXT NOT NULL,
		secret_cipher TEXT NOT NULL,
		api_key_hint VARCHAR(32) NOT NULL DEFAULT '',
		created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
		updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
		PRIMARY KEY (user_id, exchange),
		CONSTRAINT fk_credentials_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci`,

	`CREATE TABLE IF NOT EXISTS backtest_runs (
		id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
		user_id BIGINT UNSIGNED NOT NULL,
		strategy VARCHAR(64) NOT NULL,
		symbols JSON NOT NULL,
		params JSON NOT NULL,
		report_dir VARCHAR(512) NULL,
		total_return DOUBLE NULL,
		final_equity DOUBLE NULL,
		result_json MEDIUMTEXT NOT NULL,
		created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
		PRIMARY KEY (id),
		KEY idx_runs_user_created (user_id, created_at),
		CONSTRAINT fk_runs_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
	) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci`,
}
