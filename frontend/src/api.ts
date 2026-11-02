import type {
  BacktestReport,
  BacktestRequest,
  CollectorStatus,
  CredentialsInfo,
  KlineResponse,
  KlineSymbols,
  StrategySpec,
  User,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("无法连接后端 API，请确认 Go 服务已启动", 0);
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event("auth:expired"));
    }
    throw new ApiError(payload.error || `请求失败（HTTP ${response.status}）`, response.status);
  }
  return payload as T;
}

export interface AuthResponse {
  user: User;
}

export function getAuthStatus(): Promise<{ needs_setup: boolean }> {
  return request("/auth/status");
}

export function login(email: string, password: string): Promise<AuthResponse> {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function bootstrap(email: string, password: string): Promise<AuthResponse> {
  return request("/auth/bootstrap", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return request("/auth/logout", { method: "POST" });
}

export function getMe(): Promise<AuthResponse> {
  return request("/auth/me");
}

export function listUsers(): Promise<User[]> {
  return request("/users");
}

export function createUser(
  email: string,
  password: string,
  role: "admin" | "user"
): Promise<AuthResponse> {
  return request("/users", {
    method: "POST",
    body: JSON.stringify({ email, password, role }),
  });
}

export function getCredentials(): Promise<CredentialsInfo> {
  return request("/me/credentials");
}

export function putCredentials(body: {
  api_key: string;
  secret: string;
  label: string;
}): Promise<CredentialsInfo> {
  return request("/me/credentials", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function deleteCredentials(): Promise<void> {
  return request("/me/credentials", { method: "DELETE" });
}

export function getKlines(query: {
  symbol: string;
  interval: string;
  days: number;
}): Promise<KlineResponse> {
  const params = new URLSearchParams({
    symbol: query.symbol,
    interval: query.interval,
    days: String(query.days),
  });
  return request(`/klines?${params}`);
}

export function getKlineSymbols(interval: string): Promise<KlineSymbols> {
  const params = new URLSearchParams({ interval });
  return request(`/klines/symbols?${params}`);
}

export function getCollectorStatus(interval = "1m"): Promise<CollectorStatus> {
  const params = new URLSearchParams({ interval });
  return request(`/collector?${params}`);
}

export function getStrategies(): Promise<StrategySpec[]> {
  return request<StrategySpec[]>("/strategies");
}

export function runBacktest(body: BacktestRequest): Promise<BacktestReport> {
  return request<BacktestReport>("/backtests", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getHealth(): Promise<{ status: string; version: string; time: string }> {
  return request("/health");
}
