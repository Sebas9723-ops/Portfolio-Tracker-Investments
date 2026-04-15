-- Add ticker_weight_rules column to user_settings
ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS ticker_weight_rules JSONB DEFAULT '{}'::jsonb;
