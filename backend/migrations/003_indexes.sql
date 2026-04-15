-- ============================================================
-- Performance Indexes
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_transactions_user     ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_ticker   ON transactions(ticker);
CREATE INDEX IF NOT EXISTS idx_transactions_date     ON transactions(date DESC);
CREATE INDEX IF NOT EXISTS idx_positions_user        ON positions(user_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_user_date   ON portfolio_snapshots(user_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_watchlist_user        ON watchlist(user_id);
CREATE INDEX IF NOT EXISTS idx_dividends_user        ON dividends(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_user           ON alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_price_cache_fetched   ON price_cache(fetched_at);
