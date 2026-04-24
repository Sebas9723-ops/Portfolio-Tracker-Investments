-- Migration 008: Update quant_results for 4-state HMM regime labels
-- The original schema only allowed 'bull' and 'bear' — the QuantEngine now
-- produces bull_strong | bull_weak | bear_mild | crisis
-- Also adds regime_probs column for full probability vector storage.

-- 1. Drop the old CHECK constraint on regime
ALTER TABLE public.quant_results
    DROP CONSTRAINT IF EXISTS quant_results_regime_check;

-- 2. Update the CHECK to include all 6 possible regime labels
--    (original 2 + new 4, so existing rows stay valid)
ALTER TABLE public.quant_results
    ADD CONSTRAINT quant_results_regime_check
    CHECK (regime IN ('bull', 'bear', 'bull_strong', 'bull_weak', 'bear_mild', 'crisis'));

-- 3. Add regime_probs column (JSON probability vector per state)
ALTER TABLE public.quant_results
    ADD COLUMN IF NOT EXISTS regime_probs JSONB NOT NULL DEFAULT '{}';
