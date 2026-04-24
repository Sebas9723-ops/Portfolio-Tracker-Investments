-- Migration 009: add invested_base to portfolio_snapshots
-- Tracks capital invested (shares × avg_cost × FX) per day for chart history.

ALTER TABLE public.portfolio_snapshots
  ADD COLUMN IF NOT EXISTS invested_base NUMERIC;
