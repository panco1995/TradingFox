export interface ParamProperty {
  type?: string;
  title?: string;
  description?: string;
  minimum?: number;
  maximum?: number;
  default?: unknown;
  enum?: unknown[];
}

export interface StrategySpec {
  name: string;
  title: string;
  description: string;
  version: string;
  tags: string[];
  params_schema: {
    type: string;
    properties?: Record<string, ParamProperty>;
    required?: string[];
  };
  defaults: Record<string, unknown>;
}

export interface CurvePoint {
  t: string;
  v: number;
}

export interface Trade {
  time: string;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  fee: number;
  realized_pnl: number;
  reason: string;
}

export interface BacktestReport {
  strategy: string;
  symbols: string[];
  params: Record<string, unknown>;
  initial_cash: number;
  final_equity: number;
  bars_processed: number;
  start: string | null;
  end: string | null;
  metrics: Record<string, number | null>;
  monthly_returns: Record<string, number>;
  equity_curve: CurvePoint[];
  drawdown_curve: CurvePoint[];
  trades: Trade[];
  trades_total: number;
  report_dir: string | null;
}

export interface BacktestRequest {
  strategy: string;
  symbols: string[];
  days: number;
  interval: string;
  initial_cash: number;
  fee_rate: number;
  slippage_bps: number;
  params: Record<string, unknown>;
}

export interface User {
  id: number;
  email: string;
  role: "admin" | "user";
  status: string;
  created_at: string;
}

export interface KlineBar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
  closed?: boolean;
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  start: string | null;
  end: string | null;
  count: number;
  truncated: boolean;
  aggregated: boolean;
  bars: KlineBar[];
}

export interface KlineSymbols {
  interval: string;
  symbols: string[];
}

export interface CollectorInfo {
  running: boolean;
  state: string | null;
  heartbeat_at: string | null;
  heartbeat_age_seconds: number | null;
  started_at: string | null;
  pid: number | null;
  uptime_s: number | null;
  connects: number | null;
  messages: number | null;
  bars_seen: number | null;
  bars_written: number | null;
  backfills: number | null;
  idle_s: number | null;
  symbols: string[];
  follows_config?: boolean | null;
}

export interface SymbolCoverage {
  symbol: string;
  bars: number;
  first: string | null;
  last: string | null;
  close: number | null;
  lag_seconds: number | null;
  stale: boolean | null;
  bytes: number;
  files: number;
  subscribed: boolean;
}

export interface BackfillSpan {
  start: string;
  end: string;
  missing_bars: number;
}

export interface BackfillPlan {
  symbol: string;
  interval: string;
  window_start: string;
  window_end: string;
  bars_present: number;
  bars_expected: number;
  missing_bars: number;
  ratio: number;
  complete: boolean;
  missing_head: boolean;
  missing_tail: boolean;
  spans: BackfillSpan[];
}

export interface BackfillJob {
  symbol: string;
  state: "pending" | "running" | "done" | "error";
  started_at: string;
  ended_at: string | null;
  result: {
    symbol?: string;
    fetched_bars?: number;
    rows_added?: number;
    rows_updated?: number;
    spans_done?: number;
    skipped?: boolean;
    error?: string | null;
    before?: BackfillPlan;
  } | null;
  error?: string;
}

export interface SymbolMutation {
  symbols: string[];
  message: string;
  symbol: string | null;
  info?: {
    symbol?: string;
    base_asset?: string;
    quote_asset?: string;
    status?: string;
  } | null;
}

export interface CollectorStatus {
  interval: string;
  now: string;
  collector: CollectorInfo;
  configured_symbols?: string[];
  warning?: string;
  symbols: SymbolCoverage[];
}

export interface CredentialsInfo {
  exchange: string;
  configured: boolean;
  api_key_hint?: string;
  label?: string;
  updated_at?: string;
}
