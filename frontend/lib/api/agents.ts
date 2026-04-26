import { apiClient } from "./client";

export interface RiskAssessment {
  risk_level: "verde" | "amarillo" | "rojo";
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
