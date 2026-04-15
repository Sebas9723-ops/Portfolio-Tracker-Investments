-- ============================================================
-- Row Level Security Policies
-- Run AFTER 001_initial_schema.sql
-- ============================================================

ALTER TABLE user_settings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions          ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_balances      ENABLE ROW LEVEL SECURITY;
ALTER TABLE dividends          ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE watchlist          ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts             ENABLE ROW LEVEL SECURITY;
-- price_cache has no user_id — no RLS

CREATE POLICY "own_settings"   ON user_settings      FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_positions"  ON positions          FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_txns"       ON transactions       FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_cash"       ON cash_balances      FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_dividends"  ON dividends          FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_snapshots"  ON portfolio_snapshots FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_watchlist"  ON watchlist          FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own_alerts"     ON alerts             FOR ALL USING (auth.uid() = user_id);
