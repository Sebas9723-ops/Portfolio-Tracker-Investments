-- 006_target_return_and_adjustment.sql
-- 1. Add target_return column to user_settings (used by profile optimizer)
-- 2. Add ADJUSTMENT to transactions action CHECK constraint (used by manage page audit trail)

-- ── user_settings: target_return ──────────────────────────────────────────────
ALTER TABLE user_settings
  ADD COLUMN IF NOT EXISTS target_return DECIMAL(8,4) DEFAULT 0.08;

-- ── transactions: allow ADJUSTMENT action ─────────────────────────────────────
-- Drop the existing CHECK constraint and recreate with ADJUSTMENT included.
ALTER TABLE transactions DROP CONSTRAINT IF EXISTS transactions_action_check;

ALTER TABLE transactions
  ADD CONSTRAINT transactions_action_check
  CHECK (action IN ('BUY', 'SELL', 'DIVIDEND', 'SPLIT', 'FEE', 'ADJUSTMENT'));
