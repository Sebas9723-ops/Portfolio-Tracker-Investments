// ── Market ────────────────────────────────────────────────────────────────────

export interface QuoteResponse {
  ticker: string;
  price: number;
  change: number | null;
  change_pct: number | null;
  prev_close: number | null;
  currency: string;
  source: string;
  delay_minutes: number;
  as_of: string | null;
}

export interface HistoricalBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface HistoricalResponse {
  ticker: string;
  period: string;
  currency: string;
  bars: HistoricalBar[];
}

export interface MarketStatus {
  us_open: boolean;
  london_open: boolean;
  frankfurt_open: boolean;
}

// ── Portfolio ─────────────────────────────────────────────────────────────────

export interface PortfolioRow {
  ticker: string;
  name: string;
  shares: number;
  currency: string;
  market: string;
  price_native: number;
  price_base: number;
  fx_rate: number;
  avg_cost_native: number | null;
  avg_cost_base: number | null;
  value_native: number;
  value_base: number;
  invested_base: number | null;
  unrealized_pnl: number | null;
  unrealized_pnl_pct: number | null;
  weight: number;
  change_pct_1d: number | null;
  data_source: string;
}

export interface PortfolioSummary {
  rows: PortfolioRow[];
  total_value_base: number;
  total_invested_base: number | null;
  total_unrealized_pnl: number | null;
  total_unrealized_pnl_pct: number | null;
  total_day_change_base: number | null;
  base_currency: string;
  as_of: string;
}

export interface Position {
  id: string;
  ticker: string;
  name: string;
  shares: number;
  avg_cost_native: number | null;
  currency: string;
  market: string;
}

export interface Snapshot {
  id: string;
  snapshot_date: string;
  total_value_base: number | null;
  base_currency: string;
  created_at: string;
}

// ── Transactions ──────────────────────────────────────────────────────────────

export type TransactionAction = "BUY" | "SELL" | "DIVIDEND" | "SPLIT" | "FEE";

export interface Transaction {
  id: string;
  ticker: string;
  date: string;
  action: TransactionAction;
  quantity: number;
  price_native: number;
  fee_native: number;
  currency: string;
  comment: string | null;
  created_at: string;
}

export interface CashBalance {
  currency: string;
  amount: number;
  account_name: string | null;
}

// ── Analytics ─────────────────────────────────────────────────────────────────

export interface PerformanceMetrics {
  twr: number | null;
  mwr: number | null;
  annualized_return: number | null;
  annualized_vol: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  calmar: number | null;
  alpha: number | null;
  beta: number | null;
  information_ratio: number | null;
  benchmark_ticker: string;
  period: string;
}

export interface RollingPoint {
  date: string;
  sharpe: number | null;
  sortino: number | null;
  volatility: number | null;
  drawdown: number | null;
}

export interface MonthlyReturn {
  year: number;
  month: number;
  portfolio_return: number | null;
  benchmark_return: number | null;
}

export interface DrawdownEpisode {
  start: string;
  trough: string;
  end: string | null;
  depth: number;
  duration_days: number;
  recovery_days: number | null;
}

export interface AnalyticsResponse {
  metrics: PerformanceMetrics;
  rolling: RollingPoint[];
  monthly_returns: MonthlyReturn[];
  drawdown_episodes: DrawdownEpisode[];
  portfolio_series: Array<{ date: string; value: number; label: string }>;
  benchmark_series: Array<{ date: string; value: number; label: string }>;
}

// ── Optimization ──────────────────────────────────────────────────────────────

export interface FrontierPoint {
  ret: number;
  vol: number;
  sharpe: number;
  weights: Record<string, number>;
}

export interface OptimizationResult {
  frontier: FrontierPoint[];
  max_sharpe: FrontierPoint;
  min_vol: FrontierPoint;
  risk_parity: Record<string, number>;
  current_weights: Record<string, number>;
  current_metrics: Record<string, number>;
}

// ── Risk ──────────────────────────────────────────────────────────────────────

export interface VaRResult {
  confidence: number;
  var_historical: number;
  var_parametric: number;
  cvar_historical: number;
  cvar_parametric: number;
  period_days: number;
}

export interface StressTestRow {
  scenario: string;
  portfolio_impact_pct: number;
  portfolio_impact_base: number;
  details: Record<string, number>;
}

export interface RebalancingRow {
  ticker: string;
  name: string;
  current_weight: number;
  target_weight: number;
  drift: number;
  value_base: number;
  trade_value: number;
  trade_direction: string;
  estimated_tc: number;
}

// ── Settings ──────────────────────────────────────────────────────────────────

export interface UserSettings {
  base_currency: string;
  rebalancing_threshold: number;
  max_single_asset: number;
  min_bonds: number;
  min_gold: number;
  preferred_benchmark: string;
  risk_free_rate: number;
  rolling_window: number;
  tc_model: string;
  investor_profile: string;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
}
