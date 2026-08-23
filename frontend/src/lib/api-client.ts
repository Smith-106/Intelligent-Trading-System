/**
 * Type-safe API client for QuantFlow Station backend.
 * Maps 1:1 to the 18 endpoints defined in quantflow/web/app.py.
 */

const BASE = "";

const DEFAULT_TIMEOUT = 30_000; // 30s 默认超时

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { signal: customSignal, ...restOptions } = options;

  // P1 H5: 默认超时 + 支持外部 signal 透传
  const timeoutSignal = AbortSignal.timeout(DEFAULT_TIMEOUT);
  const finalSignal = customSignal
    ? AbortSignal.any([customSignal, timeoutSignal])
    : timeoutSignal;

  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    signal: finalSignal,
    ...restOptions,
  });
  const rawText = await response.text();
  let payload: unknown = null;
  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch {
      payload = { rawText };
    }
  }
  if (!response.ok) {
    const error = payload as { error?: string; message?: string };
    const rawText =
      typeof (payload as { rawText?: unknown })?.rawText === "string"
        ? `: ${(payload as { rawText: string }).rawText.slice(0, 200)}`
        : "";
    throw new Error(
      error?.error ?? error?.message ?? `Request failed (${response.status})${rawText}`,
    );
  }
  return payload as T;
}

function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  return signal ? request<T>(path, { signal }) : request<T>(path);
}

function post<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const options: RequestInit = {
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
  };
  if (signal) options.signal = signal;
  return request<T>(path, options);
}

// ── API Types ──────────────────────────────────────────────

export interface Strategy {
  strategy_id: string;
  title: string;
  description: string;
  timeframe: string | null;
  default_symbol: string | null;
  symbols: string[];
  param_space: Record<string, unknown>;
  params: Record<string, unknown>;
  exit: Record<string, unknown>;
  risk: Record<string, unknown>;
  config_path: string;
}

export interface OverviewData {
  version: string;
  phase: string;
  docker_available: boolean;
  monitoring: {
    prometheus_port: number;
    grafana_port: number;
    grafana_url: string;
    prometheus_url: string;
  };
  data: {
    parquet_dir: string;
    duckdb_path: string;
    mode: string;
    symbol_count: number;
    source_counts: Record<string, number>;
    source_context: { title: string; message: string };
    symbols: Array<{
      symbol: string;
      files: number;
      date_range: [number, number] | null;
      data_source: string;
      source_breakdown: Record<string, number>;
    }>;
  };
  risk: {
    max_drawdown: number;
    daily_loss_limit: number;
    weekly_loss_limit: number;
    kill_switch_enabled: boolean;
  };
  execution: {
    mode: string;
    slippage: number;
    maker_fee: number;
    taker_fee: number;
  };
  strategies: {
    count: number;
    items: Array<{
      strategy_id: string;
      title: string;
      description: string;
      symbols: string[];
      timeframes: string[];
    }>;
  };
}

export interface DataSnapshot {
  captured_at: string;
  mode: string;
  source_context: { title: string; message: string };
  summary: {
    symbol_count: number;
    files_total: number;
    earliest_bar_at: string | null;
    latest_bar_at: string | null;
    parquet_root_exists: boolean;
    duckdb_exists: boolean;
    source_counts: Record<string, number>;
    market_symbol_count: number;
    demo_symbol_count: number;
    unknown_symbol_count: number;
    hybrid_symbol_count: number;
  };
  storage: {
    parquet_dir: string;
    duckdb_path: string;
    config_path: string;
    execution_mode: string;
    source_mix: Record<string, number>;
  };
  leaders: {
    latest_symbol: DataSymbol | null;
    widest_symbol: DataSymbol | null;
  };
  highlights: string[];
  symbols: DataSymbol[];
}

export interface DataSymbol {
  symbol: string;
  files: number;
  range_start: string | null;
  range_end: string | null;
  coverage_days: number | null;
  last_bar_age_days: number | null;
  data_source: string;
  source_breakdown: Record<string, number>;
}

export interface DataDownloadRequest {
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
}

export interface DataDownloadResponse {
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  rows_saved: number;
  raw_rows: number;
  data_source: string;
  parquet_dir: string;
  duckdb_path: string;
  date_range: { start: string | null; end: string | null };
}

export interface ResearchRequest {
  strategy: string;
  symbol: string;
  capital: number;
  fee: number;
  start?: string;
  end?: string;
  params?: Record<string, unknown>;
}

export interface ResearchResult {
  record_id?: string;
  strategy: string;
  symbol: string;
  capital: number;
  metrics: Record<string, unknown>;
  report: string;
  chart_data?: unknown;
  [key: string]: unknown;
}

export interface ValidationRequest {
  strategy: string;
  symbol: string;
  method: string;
  optimize_trials: number;
  wfo_windows: number;
  capital: number;
  params?: Record<string, unknown>;
}

export interface ValidationResult {
  decision: string;
  reason: string;
  method: string;
  metrics: Record<string, unknown>;
  [key: string]: unknown;
}

export interface HistoryItem {
  record_id: string;
  [key: string]: unknown;
}

export interface SessionStartRequest {
  mode: string;
  strategies: string[];
  symbol: string;
  timeframe: string;
  interval_seconds: number;
  capital: number;
}

export interface SessionSnapshot {
  running: boolean;
  session_id?: string;
  started_at?: string;
  mode?: string;
  symbol?: string;
  timeframe?: string;
  portfolio: {
    cash: number;
    equity: number;
    drawdown: number;
  };
  health: {
    pending_orders: number;
  };
  positions: Array<{
    symbol: string;
    side: string;
    quantity: number;
    notional: number;
    entry_price: number;
    current_price: number;
    unrealized_pnl: number;
    pnl_pct: number;
  }>;
  open_orders: Array<{
    order_id: string;
    symbol: string;
    order_type: string;
    side: string;
    quantity: number;
    price: number;
    status: string;
  }>;
  recent_events: Array<Record<string, unknown>>;
  last_error?: string;
  [key: string]: unknown;
}

export interface MonitoringSnapshot {
  captured_at: string;
  health: {
    overall_label: string;
    overall_tone: string;
    summary: string;
    signals: string[];
  };
  metrics: {
    services_up: number;
    services_total: number;
    validation_no_go: number;
    validation_go: number;
    warning_events: number;
    error_events: number;
    research_runs: number;
    validation_runs: number;
    session_runs: number;
    session_events: number;
  };
  platform: {
    version: string;
    phase: string;
    config_path: string;
    docker_available: boolean;
    data_mode: string;
    symbol_count: number;
    source_counts: Record<string, number>;
    source_context: { title: string; message: string };
    execution_mode: string;
    kill_switch_enabled: boolean;
  };
  runtime: {
    active_session: boolean;
    session_id: string | null;
    open_positions: number;
    pending_orders: number;
    status_label: string;
    status_tone: string;
  };
  services: Array<{
    service_id: string;
    label: string;
    port: number | null;
    url: string | null;
    reachable: boolean;
    status_kind: string;
    status_label: string;
    tone: string;
    note: string;
    status_hint: string;
  }>;
  activity: {
    event_levels: Record<string, number>;
    event_types: Record<string, number>;
    validation_outcomes: Record<string, number>;
  };
  internal_metrics: {
    available: boolean;
    portfolio_value: number | null;
    portfolio_cash: number | null;
    portfolio_drawdown: number | null;
    positions_count: number | null;
    orders_total: number;
    orders_filled_total: number;
    signals_generated_total: number;
    risk_events_total: number;
    order_latency_count: number;
    order_latency_avg: number | null;
    bar_latency_count: number;
    bar_latency_avg: number | null;
    signal_latency_count: number;
    signal_latency_avg: number | null;
  };
  alerts: Array<{
    source: string;
    title: string;
    message: string;
    created_at: string;
    tone: string;
  }>;
  latest: {
    research: Record<string, unknown> | null;
    validation: Record<string, unknown> | null;
    session: Record<string, unknown> | null;
  };
}

export interface ExecutionSnapshot {
  captured_at: string;
  status: {
    label: string;
    tone: string;
    summary: string;
    session_label: string;
    session_tone: string;
  };
  summary: {
    mode: string;
    symbol: string;
    timeframe: string;
    strategy_text: string;
    position_count: number;
    order_count: number;
    gross_notional: number;
    pending_notional: number;
    unrealized_pnl: number;
    equity: number;
    cash: number;
    drawdown: number;
    exposure_pct: number;
  };
  control: {
    running: boolean;
    session_id: string | null;
    mode: string;
    symbol: string;
    timeframe: string;
    interval_seconds: number;
    capital: number;
    strategies: string[];
    config_text: string;
    strategy_text: string;
    status_note: string;
    status_tone: string;
    uptime_label: string;
    recent_event_count: number;
    open_positions: number;
    pending_orders: number;
    gross_exposure_value: number;
    net_exposure_value: number;
  };
  telemetry: {
    point_count: number;
    labels: string[];
    equity: number[];
    cash: number[];
    market_value: number[];
    drawdown: number[];
    open_positions: number[];
    pending_orders: number[];
    equity_last: number;
    cash_last: number;
    market_value_last: number;
    drawdown_last: number;
  };
  risk: {
    kill_switch_active: boolean;
    kill_switch_reason: string | null;
    drawdown_ok: boolean;
    warning_events: number;
    error_events: number;
  };
  positions: Array<{
    symbol: string;
    side: string;
    quantity: number;
    entry_price: number;
    current_price: number;
    market_value: number;
    unrealized_pnl: number;
    pnl_pct: number;
  }>;
  orders: Array<{
    order_id: string;
    symbol: string;
    side: string;
    order_type: string;
    quantity: number;
    price: number;
    status: string;
    notional: number;
  }>;
  events: Array<{
    event_type: string;
    level: string;
    title: string;
    message: string;
    created_at: string;
  }>;
  event_mix: {
    by_type: Record<string, number>;
    by_level: Record<string, number>;
  };
  execution_context: {
    source_type: string;
    source_label: string;
    data_source: string;
    data_mode: string;
    validation_label: string | null;
    validation_tone: string;
    validation_reason: string | null;
    validation_method: string | null;
  };
}

// ── API Endpoints ──────────────────────────────────────────

// PERF-REV015: multi-timeframe analysis (POST /api/analysis/multi-tf)
export interface MultiTfAnalysisRequest {
  symbols: string[];
  timeframes?: string[];
  start?: string;
  end?: string;
  fields?: "full" | "meta";
}

export interface MultiTfCandle {
  timestamp: number; // epoch milliseconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MultiTfTimeframeResult {
  timeframe: string;
  bars: number;
  insufficient_data?: boolean;
  warning?: string;
  last_close?: number;
  last_timestamp?: number;
  candles?: MultiTfCandle[];
}

export interface MultiTfSymbolResult {
  symbol: string;
  partial: boolean;
  warnings: string[];
  timeframes: MultiTfTimeframeResult[];
}

export interface MultiTfAnalysisResponse {
  partial: boolean;
  warnings: string[];
  results: MultiTfSymbolResult[];
}

export const api = {
  // Overview
  overview: () => get<OverviewData>("/api/overview"),
  strategies: () => get<Strategy[]>("/api/strategies"),

  // Data
  dataSnapshot: () => get<DataSnapshot>("/api/data"),
  dataDownload: (req: DataDownloadRequest) =>
    post<DataDownloadResponse>("/api/data/download", req),

  // Analysis
  // REV-017-RV4: multi-TF analysis is the heaviest endpoint (cold-cache
  // DuckDB + resampling); give it a 60s budget and let react-query's
  // abort signal cancel stale symbol switches instead of hogging the
  // backend thread pool for the full default timeout.
  analyzeMultiTf: (req: MultiTfAnalysisRequest, signal?: AbortSignal) =>
    post<MultiTfAnalysisResponse>("/api/analysis/multi-tf", req, signal),
  dataSeedDemo: (req: DataDownloadRequest) =>
    post<DataDownloadResponse>("/api/data/seed-demo", req),
  dataTagSource: (req: { symbol: string; source: string }) =>
    post<Record<string, unknown>>("/api/data/tag-source", req),

  // Research
  research: (req: ResearchRequest) =>
    post<ResearchResult>("/api/research", req),
  researchHistory: (limit = 12) =>
    get<{ items: HistoryItem[] }>(`/api/research/history?limit=${limit}`),

  // Validation
  validate: (req: ValidationRequest) =>
    post<ValidationResult>("/api/validate", req),
  validationHistory: (limit = 12) =>
    get<{ items: HistoryItem[] }>(`/api/validate/history?limit=${limit}`),

  // Workbench state
  getWorkbenchState: () =>
    get<{ state: Record<string, unknown> }>("/api/workbench/state"),
  saveWorkbenchState: (state: Record<string, unknown>) =>
    post<{ state: Record<string, unknown> }>("/api/workbench/state", state),

  // Monitoring
  monitoring: () => get<MonitoringSnapshot>("/api/monitoring"),

  // Execution
  execution: () => get<ExecutionSnapshot>("/api/execution"),

  // Session
  sessionSnapshot: () => get<SessionSnapshot>("/api/session"),
  sessionEvents: (limit = 40, sessionId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (sessionId) params.set("session_id", sessionId);
    return get<{ items: Array<Record<string, unknown>> }>(
      `/api/session/events?${params}`,
    );
  },
  sessionHistory: (limit = 12) =>
    get<{ items: HistoryItem[] }>(`/api/session/history?limit=${limit}`),
  sessionStart: (req: SessionStartRequest) =>
    post<SessionSnapshot>("/api/session/start", req),
  sessionStop: () => post<SessionSnapshot>("/api/session/stop"),
  sessionKillSwitch: (reason: string) =>
    post<Record<string, unknown>>("/api/session/kill-switch", { reason }),
};
