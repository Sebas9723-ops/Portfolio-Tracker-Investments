-- Migration 014: add external_thesis_tickers column to user_settings
-- Stores a list of tickers the user holds via external thesis (excluded from optimization & rebalancing targets)

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS external_thesis_tickers jsonb NOT NULL DEFAULT '[]'::jsonb;
