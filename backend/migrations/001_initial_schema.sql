-- ============================================================
-- Portfolio Tracker — Initial Schema
-- Run in Supabase SQL Editor (or via supabase db push)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── User Settings ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_settings (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id               UUID NOT NULL UNIQUE,
    base_currency         TEXT NOT NULL DEFAULT 'USD',
    rebalancing_threshold DECIMAL(6,4)  DEFAULT 0.05,
    max_single_asset      DECIMAL(6,4)  DEFAULT 0.30,
    min_bonds             DECIMAL(6,4)  DEFAULT 0.10,
    min_gold              DECIMAL(6,4)  DEFAULT 0.05,
    preferred_benchmark   TEXT          DEFAULT 'VOO',
    risk_free_rate        DECIMAL(8,4)  DEFAULT 0.045,
    rolling_window        INT           DEFAULT 63,
    tc_model              TEXT          DEFAULT 'broker',
    investor_profile      TEXT          DEFAULT 'balanced',
    created_at            TIMESTAMPTZ   DEFAULT NOW(),
    updated_at            TIMESTAMPTZ   DEFAULT NOW()
);

-- ── Positions (current holdings baseline) ─────────────────
CREATE TABLE IF NOT EXISTS positions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL,
    ticker          TEXT NOT NULL,
    name            TEXT,
    shares          DECIMAL(18,6) NOT NULL DEFAULT 0,
    avg_cost_native DECIMAL(18,6),
    currency        TEXT NOT NULL DEFAULT 'USD',
    market          TEXT DEFAULT 'US',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, ticker)
);

-- ── Transactions ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL,
    ticker       TEXT NOT NULL,
    date         DATE NOT NULL,
    action       TEXT NOT NULL CHECK (action IN ('BUY', 'SELL', 'DIVIDEND', 'SPLIT', 'FEE')),
    quantity     DECIMAL(18,6) NOT NULL,
    price_native DECIMAL(18,6) NOT NULL,
    fee_native   DECIMAL(18,6) DEFAULT 0,
    currency     TEXT NOT NULL,
    comment      TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── Cash Balances ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cash_balances (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL,
    currency     TEXT NOT NULL,
    amount       DECIMAL(18,6) NOT NULL DEFAULT 0,
    account_name TEXT,
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, currency, account_name)
);

-- ── Dividends ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dividends (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       UUID NOT NULL,
    ticker        TEXT NOT NULL,
    date          DATE NOT NULL,
    amount_native DECIMAL(18,6) NOT NULL,
    currency      TEXT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ── Portfolio Snapshots ────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL,
    snapshot_date   DATE NOT NULL,
    total_value_usd DECIMAL(18,6),
    total_value_base DECIMAL(18,6),
    base_currency   TEXT DEFAULT 'USD',
    holdings        JSONB,
    cash_data       JSONB,
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, snapshot_date)
);

-- ── Watchlist ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS watchlist (
    id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id  UUID NOT NULL,
    ticker   TEXT NOT NULL,
    name     TEXT,
    category TEXT DEFAULT 'custom',
    added_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, ticker)
);

-- ── Price Cache (shared, no user_id) ──────────────────────
CREATE TABLE IF NOT EXISTS price_cache (
    ticker     TEXT PRIMARY KEY,
    price      DECIMAL(18,6) NOT NULL,
    change_pct DECIMAL(10,4),
    prev_close DECIMAL(18,6),
    currency   TEXT NOT NULL,
    source     TEXT DEFAULT 'finnhub',
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── Alerts ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alerts (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL,
    ticker       TEXT NOT NULL,
    alert_type   TEXT NOT NULL CHECK (alert_type IN ('PRICE_ABOVE', 'PRICE_BELOW', 'CHANGE_PCT_UP', 'CHANGE_PCT_DOWN')),
    threshold    DECIMAL(18,6) NOT NULL,
    is_active    BOOLEAN DEFAULT TRUE,
    triggered_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── Updated-at trigger ────────────────────────────────────
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_user_settings_updated_at
    BEFORE UPDATE ON user_settings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_cash_balances_updated_at
    BEFORE UPDATE ON cash_balances
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
