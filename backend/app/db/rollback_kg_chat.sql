-- Rollback: KG Chat schema (kg_chat_sessions + kg_chat_messages)
--
-- Reverses the forward migration that created chat persistence tables.
-- Run against the database to cleanly remove chat tables and indexes.
--
-- NOTE: Does NOT drop the pg_trgm extension — other features depend on it
--       (entity search, client lookup trigram indexes).
--
-- Usage:
--   psql $DATABASE_URL -f backend/app/db/rollback_kg_chat.sql
--
-- Or programmatically via:
--   from app.db import rollback_kg_chat_schema
--   await rollback_kg_chat_schema()

BEGIN;

SET search_path TO playbook, public;

-- Drop indexes (on dependent table first)
DROP INDEX IF EXISTS playbook.kg_chat_messages_session_created_idx;

-- Drop indexes on sessions table
DROP INDEX IF EXISTS playbook.kg_chat_sessions_team_user_idx;

-- Drop tables in reverse dependency order
-- (kg_chat_messages has FK to kg_chat_sessions, so drop it first)
DROP TABLE IF EXISTS playbook.kg_chat_messages;
DROP TABLE IF EXISTS playbook.kg_chat_sessions;

COMMIT;
