-- Feature F: macro overlay per-ticker mu scaling
ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS macro_overlay jsonb DEFAULT '{}'::jsonb;

-- Feature C: drift alert settings
ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS drift_alerts_enabled boolean DEFAULT false,
  ADD COLUMN IF NOT EXISTS drift_alert_email     text    DEFAULT '',
  ADD COLUMN IF NOT EXISTS drift_alert_threshold decimal(5,4) DEFAULT 0.08;
