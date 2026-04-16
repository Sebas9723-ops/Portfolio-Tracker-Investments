-- 005_profile_constraints.sql
-- Add combination_ranges column and update ticker_weight_rules to support per-profile constraints.
--
-- ticker_weight_rules new format:
--   {profile: {ticker: {floor: float, cap: float}}}
--   e.g. {"conservative": {"VOO": {"floor": 0.10, "cap": 0.40}}}
--
-- combination_ranges new column:
--   {profile: [{id: str, tickers: [str], min: float, max: float}]}
--   e.g. {"base": [{"id": "...", "tickers": ["VOO", "VWCE"], "min": 0.40, "max": 0.58}]}

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS combination_ranges JSONB DEFAULT '{}'::jsonb;
