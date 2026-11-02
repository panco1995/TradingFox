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
}

export interface KlineResponse {
  symbol: string;
  interval: string;
  start: string | null;
  end: string | null;
  count: number;
  truncated: boolean;
  bars: KlineBar[];
}

export interface KlineSymbols {
  interval: string;
  symbols: string[];
}

export interface CredentialsInfo {
  exchange: string;
  configured: boolean;
  api_key_hint?: string;
  label?: string;
  updated_at?: string;
}
