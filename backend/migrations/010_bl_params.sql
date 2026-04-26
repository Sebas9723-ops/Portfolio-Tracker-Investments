-- Migration 010: Add Black-Litterman parameters to user_settings
-- bl_risk_aversion: risk aversion coefficient λ (default 2.5)
-- bl_tau:           uncertainty scaling τ (default 0.05)

ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS bl_risk_aversion DECIMAL(8,4) DEFAULT 2.5,
  ADD COLUMN IF NOT EXISTS bl_tau           DECIMAL(8,6) DEFAULT 0.05;
