-- Monitor state — tracks processed message timestamps to prevent duplicate alerts.
-- Replaces state.json from the standalone Alert-monitor-uae repo.
-- Pruning: rows older than 30 days are deleted on each run (matches original logic).

CREATE TABLE IF NOT EXISTS monitor_state (
  ts         text        NOT NULL,
  channel_id text        NOT NULL,
  created_at timestamptz DEFAULT now(),
  PRIMARY KEY (ts, channel_id)
);

CREATE INDEX IF NOT EXISTS idx_monitor_state_created_at ON monitor_state (created_at);
