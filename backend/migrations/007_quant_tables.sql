-- Migration 007: Quant optimization tables
-- Tables: quant_results, contribution_plans, bl_views

-- ── quant_results ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.quant_results (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT now(),
    profile             TEXT NOT NULL CHECK (profile IN ('conservative', 'base', 'aggressive', 'balanced')),
    regime              TEXT NOT NULL CHECK (regime IN ('bull', 'bear')),
    regime_confidence   DOUBLE PRECISION NOT NULL,
    optimal_weights     JSONB NOT NULL DEFAULT '{}',
    expected_return     DOUBLE PRECISION,
    expected_volatility DOUBLE PRECISION,
    expected_sharpe     DOUBLE PRECISION,
    cvar_95             DOUBLE PRECISION,
    correlation_alerts  JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS quant_results_user_ts
    ON public.quant_results (user_id, timestamp DESC);

-- RLS
ALTER TABLE public.quant_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "quant_results_user_select"
    ON public.quant_results FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "quant_results_service_all"
    ON public.quant_results FOR ALL
    USING (true)
    WITH CHECK (true);


-- ── contribution_plans ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.contribution_plans (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
    available_cash   DOUBLE PRECISION NOT NULL,
    total_slippage   DOUBLE PRECISION NOT NULL DEFAULT 0,
    net_invested     DOUBLE PRECISION NOT NULL DEFAULT 0,
    allocations      JSONB NOT NULL DEFAULT '[]',
    quant_result_id  UUID REFERENCES public.quant_results(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS contribution_plans_user_ts
    ON public.contribution_plans (user_id, timestamp DESC);

-- RLS
ALTER TABLE public.contribution_plans ENABLE ROW LEVEL SECURITY;

CREATE POLICY "contribution_plans_user_select"
    ON public.contribution_plans FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "contribution_plans_service_all"
    ON public.contribution_plans FOR ALL
    USING (true)
    WITH CHECK (true);


-- ── bl_views ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bl_views (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    expected_return DOUBLE PRECISION NOT NULL,   -- annualized, e.g. 0.12 = 12%
    confidence      DOUBLE PRECISION NOT NULL CHECK (confidence > 0 AND confidence <= 1),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, ticker)
);

CREATE INDEX IF NOT EXISTS bl_views_user
    ON public.bl_views (user_id);

-- RLS
ALTER TABLE public.bl_views ENABLE ROW LEVEL SECURITY;

CREATE POLICY "bl_views_user_all"
    ON public.bl_views FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "bl_views_service_all"
    ON public.bl_views FOR ALL
    USING (true)
    WITH CHECK (true);
