import { apiClient } from "./client";

export interface RiskAssessment {
  risk_level: "green" | "yellow" | "red";
  top_risk: string;
  narrative: string;
}

export interface AgentAnalysisResult {
  thesis: string | null;
  risk: RiskAssessment | null;
  research: Record<string, string> | null;
  tickers_analyzed: string[];
}

export interface AgentAnalysisRequest {
  allocations: {
    ticker: string;
    pct_of_capital?: number;
    expected_return_pct?: number;
    signals?: string[];
    current_weight?: number;
    target_weight?: number;
    gross_amount?: number;
  }[];
  regime?: string | null;
  regime_confidence?: number;
  regime_probs?: Record<string, number>;
  profile?: string;
  total_value?: number;
  total_cash?: number;
  expected_sharpe?: number;
  cvar_95?: number;
  n_corr_alerts?: number;
  correlation_alerts?: Record<string, unknown>[];
  base_currency?: string;
}

export const runAgentAnalysis = (req: AgentAnalysisRequest) =>
  apiClient
    .post<AgentAnalysisResult>("/api/agents/analyze", req, { timeout: 90_000 })
    .then((r) => r.data);

export interface MacroAgentResult {
  macro_regime: "risk_on" | "risk_off" | "stagflation" | "goldilocks" | "crisis";
  narrative: string;
  suggested_overlay: Record<string, number>;
}

export interface DoctorAgentResult {
  urgency: "low" | "medium" | "high";
  diagnosis: string;
  actions: string[];
}

export interface AgentResultRow<T> {
  id: string;
  user_id: string;
  run_at: string;
  agent_type: string;
  result: T;
  triggered_by: string;
}

export interface LastAgentResults {
  macro: AgentResultRow<MacroAgentResult> | null;
  doctor: AgentResultRow<DoctorAgentResult> | null;
}

export const fetchLastAgentResults = () =>
  apiClient.get<LastAgentResults>("/api/agents/last-results").then((r) => r.data);

export const runAgentsNow = () =>
  apiClient
    .post<{ macro: MacroAgentResult | null; doctor: DoctorAgentResult | null; errors?: string[] }>("/api/agents/run-now", {}, { timeout: 90_000 })
    .then((r) => r.data);

export interface ResearchTargetSummary {
  regime: string;
  expected_sharpe: number;
  n_targets: number;
}

export const refreshResearchTargets = () =>
  apiClient
    .post<{
      results: Record<string, ResearchTargetSummary>;
      errors: string[];
    }>("/api/agents/refresh-targets", {}, { timeout: 120_000 })
    .then((r) => r.data);

export interface TickerResearchSignal {
  score: number;
  momentum_signal: "bullish" | "neutral" | "bearish";
  fundamental_signal: "strong" | "moderate" | "weak";
  quality_signal: "high" | "medium" | "low";
  valuation_signal: "undervalued" | "fair" | "overvalued";
  weight_adjustment: number;
  key_insight: string;
}

export type ContributionResearchResult = Record<string, TickerResearchSignal>;

export const runContributionResearch = (
  allocations: { ticker: string; pct_of_capital?: number; [key: string]: unknown }[],
  profile: string,
  base_currency = "USD",
) =>
  apiClient
    .post<ContributionResearchResult>(
      "/api/agents/contribution-research",
      { allocations, profile, base_currency },
      { timeout: 90_000 },
    )
    .then((r) => r.data);
