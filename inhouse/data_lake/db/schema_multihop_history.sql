-- Application-owned semantic history for the optional PostgresHistoryStore.
-- Apply explicitly in the chatbot-owned schema; this is not part of the KOMIS
-- public data schema and is intentionally not executed by application startup.

CREATE SCHEMA IF NOT EXISTS ai_chatbot;

CREATE TABLE IF NOT EXISTS ai_chatbot.multihop_semantic_turn (
  session_id          VARCHAR(128) NOT NULL,
  turn_id             VARCHAR(128) NOT NULL,
  utterance           TEXT NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL,
  program_json        JSONB,
  pipe_id             VARCHAR(128),
  pipe_summary_json   JSONB,
  result_json         JSONB,
  evidence_json       JSONB,
  expires_at          TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (session_id, turn_id)
);

CREATE INDEX IF NOT EXISTS idx_multihop_history_expiry
  ON ai_chatbot.multihop_semantic_turn (expires_at);

CREATE INDEX IF NOT EXISTS idx_multihop_history_session
  ON ai_chatbot.multihop_semantic_turn (session_id, created_at DESC);
