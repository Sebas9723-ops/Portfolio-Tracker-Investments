-- Feature D: DCA schedule table
CREATE TABLE IF NOT EXISTS dca_schedule (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  amount         float8      NOT NULL,
  day_of_month   int         NOT NULL CHECK (day_of_month BETWEEN 1 AND 28),
  tc_model       text        NOT NULL DEFAULT 'broker',
  profile        text        NOT NULL DEFAULT 'base',
  time_horizon   text        NOT NULL DEFAULT 'long',
  active         bool        NOT NULL DEFAULT true,
  last_run_at    timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT dca_schedule_unique UNIQUE (user_id)
);

-- Feature B: prediction log table
CREATE TABLE IF NOT EXISTS prediction_log (
  id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  run_at               timestamptz NOT NULL DEFAULT now(),
  quant_result_id      uuid        REFERENCES quant_results(id) ON DELETE SET NULL,
  ticker               text        NOT NULL,
  recommended_pct      float8,
  recommended_amount   float8,
  entry_price          float8,
  price_30d            float8,
  price_60d            float8,
  price_90d            float8,
  realized_return_30d  float8,
  realized_return_60d  float8,
  realized_return_90d  float8,
  CONSTRAINT prediction_log_unique UNIQUE (user_id, run_at, ticker)
);

CREATE INDEX IF NOT EXISTS prediction_log_user_run_idx ON prediction_log(user_id, run_at DESC);
