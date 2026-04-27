-- Agent results: stores scheduled and manual AI agent run outputs
CREATE TABLE IF NOT EXISTS agent_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  run_at timestamptz DEFAULT now(),
  agent_type text NOT NULL,        -- 'macro', 'doctor', 'full_pipeline'
  result jsonb NOT NULL,
  triggered_by text DEFAULT 'scheduler'  -- 'scheduler', 'manual', 'drift'
);

CREATE INDEX IF NOT EXISTS agent_results_user_type_idx
  ON agent_results (user_id, agent_type, run_at DESC);

-- RLS
ALTER TABLE agent_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_own_agent_results" ON agent_results
  FOR ALL USING (user_id = auth.uid());
