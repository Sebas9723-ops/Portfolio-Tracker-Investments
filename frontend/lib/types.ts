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
  cost_currency: string;
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
  pending_tickers: string[];  // 0-share positions (watchlist/pre-buy)
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

export type TransactionAction = "BUY" | "SELL" | "DIVIDEND" | "SPLIT" | "FEE" | "ADJUSTMENT";

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
  max_return: FrontierPoint;
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

// Legacy per-ticker fixed-weight rule (used in rebalancing page)
export interface TickerWeightRule {
  mode: "free" | "fixed";
  weight?: number;
}

export interface TickerFloorCap {
  floor: number;
  cap: number;
}

export interface CombinationRange {
  id: string;
  tickers: string[];
  min: number | null;  // null = sin límite inferior
  max: number | null;  // null = sin límite superior
}

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
  // Motor 1: {profile: {ticker: {floor, cap}}}
  ticker_weight_rules: Record<string, Record<string, TickerFloorCap>>;
  // Motor 2: {profile: CombinationRange[]}
  combination_ranges: Record<string, CombinationRange[]>;
  // Horizon planner persistent params
  horizon_params?: {
    monthly: number;
    years: number;
    vol: number;
    goal: number;
  };
  // Actual USD cost basis (set by user, persisted to Supabase — FX-correct across devices)
  cost_basis_usd?: number | null;
  // Optimization period per profile (e.g. {conservative: "2y", base: "3y"})
  optimization_periods?: Record<string, string>;
  // Quant engine time horizon (persisted)
  time_horizon?: "short" | "medium" | "long";
  // Black-Litterman views per profile
  bl_views?: Record<string, { ticker: string; ret: string }[]>;
  // Last frontier result — used by Contribution Planner (profile-aware)
  frontier_result?: {
    max_sharpe: { ret: number; vol: number; sharpe: number };
    min_vol:    { ret: number; vol: number; sharpe: number };
    max_return: { ret: number; vol: number; sharpe: number };
  };
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
}
