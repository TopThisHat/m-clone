"""
PostgreSQL connection pool and CRUD helpers for research sessions.
Uses asyncpg directly (no ORM) for simplicity and performance.

In dev, set DATABASE_URL.
In dev/uat/prod, set AWS_SECRET_NAME (and optionally AWS_REGION) instead;
the secret must be a JSON object with keys: host, port, username, password, dbname.
SSL is automatically enabled when using AWS Secrets Manager.

Password rotation is handled transparently: if a connection attempt raises an
authentication error (which is how rotation surfaces — you don't know until the
next new connection fails), the pool is torn down, the cached secret is evicted,
a fresh secret is fetched from Secrets Manager, and the pool is rebuilt.
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _pool_lock
    if _pool_lock is None:
        _pool_lock = asyncio.Lock()
    return _pool_lock


class DatabaseNotConfigured(RuntimeError):
    pass


def _resolve_connection() -> tuple[str, str | None]:
    """Return (dsn, ssl_mode). Prefers AWS secret over DATABASE_URL."""
    if settings.aws_secret_name:
        from app.secrets import build_dsn, get_db_secret
        secret = get_db_secret(settings.aws_secret_name, settings.aws_region)
        return build_dsn(secret), "require"
    if settings.database_url:
        return settings.database_url, None
    raise DatabaseNotConfigured(
        "No database configured. Set DATABASE_URL or AWS_SECRET_NAME."
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    async with _get_lock():
        if _pool is not None:  # another coroutine beat us here
            return _pool
        dsn, ssl_mode = _resolve_connection()
        kwargs: dict[str, Any] = {"dsn": dsn}
        if ssl_mode:
            kwargs["ssl"] = ssl_mode
        _pool = await asyncpg.create_pool(**kwargs)
        logger.info("DB pool created (ssl=%s)", ssl_mode or "off")
        return _pool


async def _reset_pool() -> None:
    """
    Tear down the current pool and evict the cached secret so that the next
    get_pool() call re-fetches credentials and creates a fresh pool.
    Called automatically when a credential-rotation auth error is detected.
    """
    global _pool
    async with _get_lock():
        old_pool, _pool = _pool, None
        if settings.aws_secret_name:
            from app.secrets import invalidate_db_secret
            invalidate_db_secret()
    if old_pool is not None:
        try:
            await old_pool.close()
        except Exception:
            pass
    logger.warning("DB pool reset — fresh credentials will be fetched on next request")


# Errors that indicate the password has changed (rotation).
# asyncpg raises InvalidPasswordError when it can't authenticate a new connection.
_AUTH_ERRORS = (
    asyncpg.exceptions.InvalidPasswordError,
    asyncpg.exceptions.PostgresConnectionError,
)


@asynccontextmanager
async def _acquire():
    """
    Async context manager that yields a DB connection from the pool.

    On the first auth error (InvalidPasswordError / PostgresConnectionError) it
    assumes the secret was rotated, resets the pool, re-fetches the secret, and
    retries the acquire once before re-raising.
    """
    pool = await get_pool()
    try:
        conn = await pool.acquire()
    except _AUTH_ERRORS as exc:
        logger.warning("DB auth error — attempting rotation recovery: %s", exc)
        await _reset_pool()
        pool = await get_pool()
        conn = await pool.acquire()
    try:
        yield conn
    finally:
        await pool.release(conn)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def init_schema() -> None:
    async with _acquire() as conn:
        # Advisory lock prevents concurrent hot-reload workers from deadlocking
        # on simultaneous ALTER TABLE statements. Lock is session-scoped and
        # released automatically when the connection returns to the pool.
        await conn.execute("SELECT pg_advisory_lock(8675309)")
        try:
            await conn.execute("""
            -- Users (populated on first SSO login or dev-login)
            CREATE TABLE IF NOT EXISTS users (
                sid          TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email        TEXT,
                avatar_url   TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                last_login   TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                title            TEXT NOT NULL,
                query            TEXT NOT NULL,
                report_markdown  TEXT NOT NULL DEFAULT '',
                message_history  JSONB NOT NULL DEFAULT '[]',
                trace_steps      JSONB NOT NULL DEFAULT '[]',
                created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS sessions_updated_at_idx
                ON sessions (updated_at DESC);

            ALTER TABLE users ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT 'dark';

            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE;
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS usage_tokens INTEGER DEFAULT 0;
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_sid TEXT REFERENCES users(sid);
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';
            CREATE INDEX IF NOT EXISTS sessions_is_public_idx ON sessions (is_public) WHERE is_public;
            CREATE INDEX IF NOT EXISTS sessions_owner_idx ON sessions (owner_sid);

            CREATE TABLE IF NOT EXISTS agent_memory (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id   UUID REFERENCES sessions(id) ON DELETE CASCADE,
                entity       TEXT NOT NULL,
                entity_type  TEXT,
                facts        JSONB NOT NULL DEFAULT '[]',
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS agent_memory_entity_idx ON agent_memory (entity);

            CREATE TABLE IF NOT EXISTS research_jobs (
                id                UUID PRIMARY KEY,
                query             TEXT NOT NULL,
                webhook_url       TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'queued',
                result_markdown   TEXT NOT NULL DEFAULT '',
                error             TEXT,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at      TIMESTAMPTZ
            );

            -- Teams
            CREATE TABLE IF NOT EXISTS teams (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                slug         TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                description  TEXT DEFAULT '',
                created_by   TEXT REFERENCES users(sid),
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            -- Team membership with roles
            CREATE TABLE IF NOT EXISTS team_members (
                team_id   UUID REFERENCES teams(id) ON DELETE CASCADE,
                sid       TEXT REFERENCES users(sid) ON DELETE CASCADE,
                role      TEXT NOT NULL DEFAULT 'member',
                joined_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (team_id, sid)
            );

            -- Session <-> Team sharing
            CREATE TABLE IF NOT EXISTS session_teams (
                session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                team_id    UUID REFERENCES teams(id) ON DELETE CASCADE,
                shared_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (session_id, team_id)
            );

            -- Comments with @mentions
            CREATE TABLE IF NOT EXISTS comments (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                author_sid TEXT REFERENCES users(sid),
                body       TEXT NOT NULL,
                mentions   JSONB NOT NULL DEFAULT '[]',
                parent_id  UUID REFERENCES comments(id),
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS comments_session_idx ON comments (session_id);

            -- Pinned sessions per user
            CREATE TABLE IF NOT EXISTS pinned_sessions (
                sid        TEXT REFERENCES users(sid) ON DELETE CASCADE,
                session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                team_id    UUID REFERENCES teams(id) ON DELETE CASCADE,
                pinned_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (sid, session_id, team_id)
            );

            -- Notifications (polled every 30s)
            CREATE TABLE IF NOT EXISTS notifications (
                id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                recipient_sid TEXT REFERENCES users(sid) ON DELETE CASCADE,
                type          TEXT NOT NULL,
                payload       JSONB NOT NULL DEFAULT '{}',
                read          BOOLEAN DEFAULT FALSE,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS notifications_recipient_idx
                ON notifications (recipient_sid, read);

            -- Team activity feed
            CREATE TABLE IF NOT EXISTS team_activity (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                team_id    UUID REFERENCES teams(id) ON DELETE CASCADE,
                actor_sid  TEXT REFERENCES users(sid),
                action     TEXT NOT NULL,
                payload    JSONB NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS team_activity_team_idx
                ON team_activity (team_id, created_at DESC);

            -- Scheduled monitors
            CREATE TABLE IF NOT EXISTS monitors (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_sid   TEXT NOT NULL,
                label       TEXT NOT NULL,
                query       TEXT NOT NULL,
                frequency   TEXT NOT NULL DEFAULT 'daily',
                last_run_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            -- ── Scout: Entity Validation & Scoring Platform ──────────────────

            CREATE TABLE IF NOT EXISTS campaigns (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_sid   TEXT NOT NULL,
                name        TEXT NOT NULL,
                description TEXT,
                schedule    TEXT,
                is_active   BOOLEAN DEFAULT TRUE,
                last_run_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS entities (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                description TEXT,
                gwm_id      TEXT,
                metadata    JSONB DEFAULT '{}',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS entities_campaign_idx ON entities(campaign_id);

            CREATE TABLE IF NOT EXISTS attributes (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                description TEXT,
                weight      FLOAT DEFAULT 1.0,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS validation_jobs (
                id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                campaign_id      UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                triggered_by     TEXT,
                triggered_sid    TEXT,
                status           TEXT DEFAULT 'queued',
                entity_filter    UUID[],
                attribute_filter UUID[],
                total_pairs      INT DEFAULT 0,
                completed_pairs  INT DEFAULT 0,
                error            TEXT,
                created_at       TIMESTAMPTZ DEFAULT NOW(),
                started_at       TIMESTAMPTZ,
                completed_at     TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS validation_results (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_id       UUID REFERENCES validation_jobs(id) ON DELETE CASCADE,
                entity_id    UUID REFERENCES entities(id) ON DELETE CASCADE,
                attribute_id UUID REFERENCES attributes(id) ON DELETE CASCADE,
                present      BOOLEAN NOT NULL,
                confidence   FLOAT,
                evidence     TEXT,
                report_md    TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (job_id, entity_id, attribute_id)
            );
            CREATE INDEX IF NOT EXISTS results_entity_attr_idx
                ON validation_results(entity_id, attribute_id);

            CREATE TABLE IF NOT EXISTS entity_scores (
                entity_id          UUID REFERENCES entities(id) ON DELETE CASCADE,
                campaign_id        UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                total_score        FLOAT DEFAULT 0,
                attributes_present INT DEFAULT 0,
                attributes_checked INT DEFAULT 0,
                last_updated       TIMESTAMPTZ,
                PRIMARY KEY (entity_id, campaign_id)
            );

            -- Global knowledge cache: gwm_id × attribute_label → research result
            -- Only updated on fresh research (not cache hits), so source reflects origin campaign
            CREATE TABLE IF NOT EXISTS entity_attribute_knowledge (
                gwm_id               TEXT NOT NULL,
                attribute_label      TEXT NOT NULL,
                present              BOOLEAN NOT NULL,
                confidence           FLOAT,
                evidence             TEXT,
                source_job_id        UUID,
                source_campaign_id   UUID,
                source_campaign_name TEXT,
                entity_label         TEXT,
                last_updated         TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (gwm_id, attribute_label)
            );

            -- ── Knowledge Graph ───────────────────────────────────────────────

            CREATE TABLE IF NOT EXISTS kg_entities (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name        TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases     TEXT[] DEFAULT '{}',
                metadata    JSONB DEFAULT '{}',
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS kg_entities_name_idx ON kg_entities (LOWER(name));

            CREATE TABLE IF NOT EXISTS kg_relationships (
                id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subject_id        UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
                predicate         TEXT NOT NULL,
                predicate_family  TEXT NOT NULL,
                object_id         UUID NOT NULL REFERENCES kg_entities(id) ON DELETE CASCADE,
                confidence        FLOAT DEFAULT 1.0,
                evidence          TEXT,
                source_session_id UUID,
                is_active         BOOLEAN DEFAULT TRUE,
                created_at        TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS kg_rel_active_family_idx
                ON kg_relationships (subject_id, object_id, predicate_family)
                WHERE is_active = TRUE;

            CREATE TABLE IF NOT EXISTS kg_relationship_conflicts (
                id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                old_relationship_id  UUID NOT NULL REFERENCES kg_relationships(id),
                new_relationship_id  UUID NOT NULL REFERENCES kg_relationships(id),
                old_predicate        TEXT NOT NULL,
                new_predicate        TEXT NOT NULL,
                subject_name         TEXT NOT NULL,
                object_name          TEXT NOT NULL,
                detected_at          TIMESTAMPTZ DEFAULT NOW()
            );

            -- ── Job Queue (PostgreSQL-native, SKIP LOCKED) ────────────────────

            CREATE TABLE IF NOT EXISTS job_queue (
                id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                job_type          TEXT NOT NULL,
                payload           JSONB NOT NULL DEFAULT '{}',
                parent_job_id     UUID REFERENCES job_queue(id) ON DELETE SET NULL,
                root_job_id       UUID REFERENCES job_queue(id) ON DELETE SET NULL,
                status            TEXT NOT NULL DEFAULT 'pending'
                                      CHECK (status IN ('pending','claimed','running','done','failed','dead')),
                attempts          INT NOT NULL DEFAULT 0,
                max_attempts      INT NOT NULL DEFAULT 3,
                last_error        TEXT,
                run_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                priority          INT NOT NULL DEFAULT 0,
                heartbeat_at      TIMESTAMPTZ,
                worker_id         TEXT,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                claimed_at        TIMESTAMPTZ,
                started_at        TIMESTAMPTZ,
                completed_at      TIMESTAMPTZ,
                validation_job_id UUID REFERENCES validation_jobs(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS job_queue_dequeue_idx
                ON job_queue (status, run_at, priority DESC, created_at ASC)
                WHERE status = 'pending';

            CREATE INDEX IF NOT EXISTS job_queue_heartbeat_idx
                ON job_queue (status, heartbeat_at)
                WHERE status IN ('claimed', 'running');

            CREATE INDEX IF NOT EXISTS job_queue_parent_idx
                ON job_queue (parent_job_id, status)
                WHERE parent_job_id IS NOT NULL;

            CREATE INDEX IF NOT EXISTS job_queue_dead_idx
                ON job_queue (status, job_type, created_at DESC)
                WHERE status = 'dead';
        """)
            # Full-text search on sessions (title + query)
            await conn.execute("""
                ALTER TABLE sessions ADD COLUMN IF NOT EXISTS search_vec tsvector
                    GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(title,'') || ' ' || coalesce(query,''))
                    ) STORED
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS sessions_search_idx ON sessions USING GIN(search_vec)
            """)
        finally:
            await conn.execute("SELECT pg_advisory_unlock(8675309)")


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("message_history", "trace_steps", "mentions", "payload", "facts"):
        if field in d and isinstance(d[field], str):
            d[field] = json.loads(d[field])
    for field in ("id", "session_id", "team_id", "parent_id", "comment_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    if "updated_at" in d and d["updated_at"] is not None:
        d["updated_at"] = d["updated_at"].isoformat()
    if "joined_at" in d and d["joined_at"] is not None:
        d["joined_at"] = d["joined_at"].isoformat()
    if "shared_at" in d and d["shared_at"] is not None:
        d["shared_at"] = d["shared_at"].isoformat()
    if "pinned_at" in d and d["pinned_at"] is not None:
        d["pinned_at"] = d["pinned_at"].isoformat()
    if "last_login" in d and d["last_login"] is not None:
        d["last_login"] = d["last_login"].isoformat()
    return d


async def db_list_sessions(owner_sid: str | None = None, search: str | None = None) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        select = (
            "SELECT id, title, query, created_at, updated_at, "
            "COALESCE(is_public, FALSE) AS is_public, COALESCE(usage_tokens, 0) AS usage_tokens, "
            "owner_sid, COALESCE(visibility, 'private') AS visibility "
            "FROM sessions "
        )
        if owner_sid and search:
            rows = await conn.fetch(
                select + "WHERE (owner_sid = $1 OR visibility = 'public') "
                "AND search_vec @@ plainto_tsquery('english', $2) "
                "ORDER BY updated_at DESC",
                owner_sid, search,
            )
        elif owner_sid:
            rows = await conn.fetch(
                select + "WHERE owner_sid = $1 OR visibility = 'public' "
                "ORDER BY updated_at DESC",
                owner_sid,
            )
        elif search:
            rows = await conn.fetch(
                select + "WHERE search_vec @@ plainto_tsquery('english', $1) "
                "ORDER BY updated_at DESC",
                search,
            )
        else:
            rows = await conn.fetch(select + "ORDER BY updated_at DESC")
    return [_row_to_dict(r) for r in rows]


async def db_get_session(session_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT *, COALESCE(is_public, FALSE) AS is_public, "
            "COALESCE(usage_tokens, 0) AS usage_tokens, "
            "COALESCE(visibility, 'private') AS visibility "
            "FROM sessions WHERE id = $1",
            session_id,
        )
    return _row_to_dict(row) if row else None


async def db_get_public_session(session_id: str) -> dict[str, Any] | None:
    """Return session only if is_public=true."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT *, COALESCE(is_public, FALSE) AS is_public, "
            "COALESCE(usage_tokens, 0) AS usage_tokens, "
            "COALESCE(visibility, 'private') AS visibility "
            "FROM sessions WHERE id = $1 AND is_public = TRUE",
            session_id,
        )
    return _row_to_dict(row) if row else None


async def db_create_session(data: dict[str, Any]) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO sessions (title, query, report_markdown, message_history, trace_steps, owner_sid, visibility)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, $7)
            RETURNING *, COALESCE(is_public, FALSE) AS is_public,
                         COALESCE(usage_tokens, 0) AS usage_tokens,
                         COALESCE(visibility, 'private') AS visibility
            """,
            data["title"],
            data["query"],
            data.get("report_markdown", ""),
            json.dumps(data.get("message_history", [])),
            json.dumps(data.get("trace_steps", [])),
            data.get("owner_sid"),
            data.get("visibility", "private"),
        )
    return _row_to_dict(row)


async def db_update_session(session_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"title", "report_markdown", "message_history", "trace_steps", "is_public", "usage_tokens", "visibility", "owner_sid"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_session(session_id)

    set_parts = []
    values: list[Any] = []
    idx = 1
    for key, val in fields.items():
        if key in ("message_history", "trace_steps"):
            set_parts.append(f"{key} = ${idx}::jsonb")
            values.append(json.dumps(val))
        else:
            set_parts.append(f"{key} = ${idx}")
            values.append(val)
        idx += 1

    set_parts.append("updated_at = NOW()")
    values.append(session_id)

    sql = (
        f"UPDATE sessions SET {', '.join(set_parts)} WHERE id = ${idx} "
        "RETURNING *, COALESCE(is_public, FALSE) AS is_public, "
        "COALESCE(usage_tokens, 0) AS usage_tokens, "
        "COALESCE(visibility, 'private') AS visibility"
    )

    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _row_to_dict(row) if row else None


async def db_delete_session(session_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)
    return result.endswith("1")


# ── Research jobs ─────────────────────────────────────────────────────────────

def _job_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat()
    if d.get("completed_at"):
        d["completed_at"] = d["completed_at"].isoformat()
    return d


async def db_create_job(job_id: str, query: str, webhook_url: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO research_jobs (id, query, webhook_url, status)
            VALUES ($1::uuid, $2, $3, 'queued')
            RETURNING *
            """,
            job_id,
            query,
            webhook_url,
        )
    return _job_row_to_dict(row)


async def db_update_job(job_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"status", "result_markdown", "error", "completed_at"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return None

    set_parts = []
    values: list[Any] = []
    idx = 1
    for key, val in fields.items():
        set_parts.append(f"{key} = ${idx}")
        values.append(val)
        idx += 1

    values.append(job_id)
    sql = f"UPDATE research_jobs SET {', '.join(set_parts)} WHERE id = ${idx} RETURNING *"

    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _job_row_to_dict(row) if row else None


async def db_get_job(job_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM research_jobs WHERE id = $1::uuid", job_id)
    return _job_row_to_dict(row) if row else None


# ── Users ──────────────────────────────────────────────────────────────────────

async def db_upsert_user(sid: str, display_name: str, email: str = "") -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (sid, display_name, email, last_login)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (sid) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                email = EXCLUDED.email,
                last_login = NOW()
            RETURNING *
            """,
            sid, display_name, email,
        )
    return _row_to_dict(row)


async def db_get_user(sid: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE sid = $1", sid)
    return _row_to_dict(row) if row else None


async def db_update_user_theme(sid: str, theme: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE users SET theme = $1 WHERE sid = $2",
            theme, sid,
        )


# ── Teams ──────────────────────────────────────────────────────────────────────

async def db_create_team(slug: str, display_name: str, description: str, created_by: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO teams (slug, display_name, description, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            slug, display_name, description, created_by,
        )
        team = _row_to_dict(row)
        # Creator becomes owner
        await conn.execute(
            "INSERT INTO team_members (team_id, sid, role) VALUES ($1, $2, 'owner')",
            row["id"], created_by,
        )
    return team


async def db_get_team(slug: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM teams WHERE slug = $1", slug)
    return _row_to_dict(row) if row else None


async def db_get_team_by_id(team_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM teams WHERE id = $1::uuid", team_id)
    return _row_to_dict(row) if row else None


async def db_list_user_teams(sid: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.*, tm.role, tm.joined_at
            FROM teams t
            JOIN team_members tm ON t.id = tm.team_id
            WHERE tm.sid = $1
            ORDER BY t.display_name
            """,
            sid,
        )
    return [_row_to_dict(r) for r in rows]


async def db_update_team(slug: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"display_name", "description"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_team(slug)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [slug]
    sql = f"UPDATE teams SET {', '.join(set_parts)} WHERE slug = ${len(values)} RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _row_to_dict(row) if row else None


async def db_delete_team(slug: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute("DELETE FROM teams WHERE slug = $1", slug)
    return result.endswith("1")


# ── Team Members ───────────────────────────────────────────────────────────────

async def db_list_team_members(team_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.sid, u.display_name, u.email, u.avatar_url,
                   tm.role, tm.joined_at
            FROM team_members tm
            JOIN users u ON tm.sid = u.sid
            WHERE tm.team_id = $1::uuid
            ORDER BY tm.role, u.display_name
            """,
            team_id,
        )
    return [_row_to_dict(r) for r in rows]


async def db_get_member_role(team_id: str, sid: str) -> str | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM team_members WHERE team_id = $1::uuid AND sid = $2",
            team_id, sid,
        )
    return row["role"] if row else None


async def db_add_member(team_id: str, sid: str, role: str = "member") -> dict[str, Any]:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO team_members (team_id, sid, role)
            VALUES ($1::uuid, $2, $3)
            ON CONFLICT (team_id, sid) DO UPDATE SET role = EXCLUDED.role
            """,
            team_id, sid, role,
        )
    return {"team_id": team_id, "sid": sid, "role": role}


async def db_update_member_role(team_id: str, sid: str, role: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "UPDATE team_members SET role = $1 WHERE team_id = $2::uuid AND sid = $3",
            role, team_id, sid,
        )
    return result.endswith("1")


async def db_remove_member(team_id: str, sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM team_members WHERE team_id = $1::uuid AND sid = $2",
            team_id, sid,
        )
    return result.endswith("1")


# ── Session ↔ Team sharing ─────────────────────────────────────────────────────

async def db_share_session_to_team(session_id: str, team_id: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO session_teams (session_id, team_id)
            VALUES ($1::uuid, $2::uuid)
            ON CONFLICT DO NOTHING
            RETURNING *
            """,
            session_id, team_id,
        )
    return {"session_id": session_id, "team_id": team_id}


async def db_unshare_session(session_id: str, team_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM session_teams WHERE session_id = $1::uuid AND team_id = $2::uuid",
            session_id, team_id,
        )
    return result.endswith("1")


async def db_get_team_sessions(team_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.title, s.query, s.created_at, s.updated_at,
                   COALESCE(s.is_public, FALSE) AS is_public,
                   COALESCE(s.usage_tokens, 0) AS usage_tokens,
                   s.owner_sid, COALESCE(s.visibility, 'private') AS visibility,
                   st.shared_at
            FROM sessions s
            JOIN session_teams st ON s.id = st.session_id
            WHERE st.team_id = $1::uuid AND s.visibility != 'private'
            ORDER BY st.shared_at DESC
            LIMIT $2 OFFSET $3
            """,
            team_id, limit, offset,
        )
    return [_row_to_dict(r) for r in rows]


async def db_get_session_teams(session_id: str) -> list[str]:
    """Return list of team_ids this session is shared to."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT team_id::text FROM session_teams WHERE session_id = $1::uuid",
            session_id,
        )
    return [r["team_id"] for r in rows]


# ── Pinned sessions ────────────────────────────────────────────────────────────

async def db_pin_session(sid: str, session_id: str, team_id: str) -> dict[str, Any]:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO pinned_sessions (sid, session_id, team_id)
            VALUES ($1, $2::uuid, $3::uuid)
            ON CONFLICT DO NOTHING
            """,
            sid, session_id, team_id,
        )
    return {"sid": sid, "session_id": session_id, "team_id": team_id}


async def db_unpin_session(sid: str, session_id: str, team_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM pinned_sessions WHERE sid = $1 AND session_id = $2::uuid AND team_id = $3::uuid",
            sid, session_id, team_id,
        )
    return result.endswith("1")


async def db_get_pinned_sessions(sid: str, team_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT s.id, s.title, s.query, s.created_at, s.updated_at,
                   COALESCE(s.is_public, FALSE) AS is_public,
                   COALESCE(s.usage_tokens, 0) AS usage_tokens,
                   s.owner_sid, COALESCE(s.visibility, 'private') AS visibility,
                   ps.pinned_at
            FROM pinned_sessions ps
            JOIN sessions s ON ps.session_id = s.id
            WHERE ps.sid = $1 AND ps.team_id = $2::uuid
            ORDER BY ps.pinned_at DESC
            """,
            sid, team_id,
        )
    return [_row_to_dict(r) for r in rows]


# ── Comments ───────────────────────────────────────────────────────────────────

async def db_create_comment(session_id: str, author_sid: str, body: str, mentions: list[str], parent_id: str | None = None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO comments (session_id, author_sid, body, mentions, parent_id)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5::uuid)
            RETURNING *
            """,
            session_id, author_sid, body, json.dumps(mentions),
            parent_id if parent_id else None,
        )
    return _row_to_dict(row)


async def db_list_comments(session_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.*, u.display_name AS author_name, u.avatar_url AS author_avatar
            FROM comments c
            LEFT JOIN users u ON c.author_sid = u.sid
            WHERE c.session_id = $1::uuid
            ORDER BY c.created_at ASC
            """,
            session_id,
        )
    result = []
    for r in rows:
        d = dict(r)
        for field in ("mentions",):
            if field in d and isinstance(d[field], str):
                d[field] = json.loads(d[field])
        for field in ("id", "session_id", "parent_id"):
            if field in d and d[field] is not None:
                d[field] = str(d[field])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        if "updated_at" in d and d["updated_at"] is not None:
            d["updated_at"] = d["updated_at"].isoformat()
        result.append(d)
    return result


async def db_get_comment(comment_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM comments WHERE id = $1::uuid", comment_id)
    return _row_to_dict(row) if row else None


async def db_delete_comment(comment_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute("DELETE FROM comments WHERE id = $1::uuid", comment_id)
    return result.endswith("1")


# ── Notifications ──────────────────────────────────────────────────────────────

async def db_create_notification(recipient_sid: str, type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO notifications (recipient_sid, type, payload)
            VALUES ($1, $2, $3::jsonb)
            RETURNING *
            """,
            recipient_sid, type_, json.dumps(payload),
        )
    return _row_to_dict(row)


async def db_list_notifications(recipient_sid: str, limit: int = 50) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM notifications
            WHERE recipient_sid = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            recipient_sid, limit,
        )
    result = []
    for r in rows:
        d = dict(r)
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


async def db_mark_notification_read(notification_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "UPDATE notifications SET read = TRUE WHERE id = $1::uuid",
            notification_id,
        )
    return result.endswith("1")


async def db_mark_all_notifications_read(recipient_sid: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE notifications SET read = TRUE WHERE recipient_sid = $1 AND read = FALSE",
            recipient_sid,
        )


# ── Team activity ──────────────────────────────────────────────────────────────

async def db_record_activity(team_id: str, actor_sid: str, action: str, payload: dict[str, Any]) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO team_activity (team_id, actor_sid, action, payload)
            VALUES ($1::uuid, $2, $3, $4::jsonb)
            """,
            team_id, actor_sid, action, json.dumps(payload),
        )


async def db_list_team_activity(team_id: str, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT ta.*, u.display_name AS actor_name, u.avatar_url AS actor_avatar
            FROM team_activity ta
            LEFT JOIN users u ON ta.actor_sid = u.sid
            WHERE ta.team_id = $1::uuid
            ORDER BY ta.created_at DESC
            LIMIT $2 OFFSET $3
            """,
            team_id, limit, offset,
        )
    result = []
    for r in rows:
        d = dict(r)
        if "id" in d and d["id"] is not None:
            d["id"] = str(d["id"])
        if "team_id" in d and d["team_id"] is not None:
            d["team_id"] = str(d["team_id"])
        if "created_at" in d and d["created_at"] is not None:
            d["created_at"] = d["created_at"].isoformat()
        if isinstance(d.get("payload"), str):
            d["payload"] = json.loads(d["payload"])
        result.append(d)
    return result


# ── Monitors ───────────────────────────────────────────────────────────────────

def _monitor_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    for ts in ("last_run_at", "next_run_at", "created_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


async def db_create_monitor(owner_sid: str, label: str, query: str, frequency: str) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO monitors (owner_sid, label, query, frequency)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            owner_sid, label, query, frequency,
        )
    return _monitor_row_to_dict(row)


async def db_list_monitors(owner_sid: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM monitors WHERE owner_sid = $1 ORDER BY created_at DESC",
            owner_sid,
        )
    return [_monitor_row_to_dict(r) for r in rows]


async def db_delete_monitor(monitor_id: str, owner_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM monitors WHERE id = $1::uuid AND owner_sid = $2",
            monitor_id, owner_sid,
        )
    return result.endswith("1")


async def db_get_due_monitors() -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM monitors WHERE next_run_at <= NOW() ORDER BY next_run_at ASC"
        )
    return [_monitor_row_to_dict(r) for r in rows]


async def db_update_monitor_run(monitor_id: str, frequency: str) -> None:
    interval = "1 day" if frequency == "daily" else "7 days"
    async with _acquire() as conn:
        await conn.execute(
            f"UPDATE monitors SET last_run_at = NOW(), next_run_at = NOW() + INTERVAL '{interval}' "
            "WHERE id = $1::uuid",
            monitor_id,
        )


# ── Scout: Campaigns ───────────────────────────────────────────────────────────

def _campaign_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "updated_at", "last_run_at", "next_run_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


async def db_create_campaign(owner_sid: str, name: str, description: str | None, schedule: str | None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO campaigns (owner_sid, name, description, schedule)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            owner_sid, name, description, schedule,
        )
    return _campaign_row_to_dict(row)


async def db_list_campaigns(owner_sid: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM campaigns WHERE owner_sid = $1 ORDER BY created_at DESC",
            owner_sid,
        )
    return [_campaign_row_to_dict(r) for r in rows]


async def db_get_campaign(campaign_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM campaigns WHERE id = $1::uuid", campaign_id)
    return _campaign_row_to_dict(row) if row else None


async def db_update_campaign(campaign_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"name", "description", "schedule", "is_active", "next_run_at"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_campaign(campaign_id)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [campaign_id]
    sql = (
        f"UPDATE campaigns SET {', '.join(set_parts)}, updated_at = NOW() "
        f"WHERE id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _campaign_row_to_dict(row) if row else None


async def db_delete_campaign(campaign_id: str, owner_sid: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM campaigns WHERE id = $1::uuid AND owner_sid = $2",
            campaign_id, owner_sid,
        )
    return result.endswith("1")


# ── Scout: Entities ────────────────────────────────────────────────────────────

def _entity_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "metadata" in d and isinstance(d["metadata"], str):
        d["metadata"] = json.loads(d["metadata"])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_create_entity(campaign_id: str, label: str, description: str | None = None,
                           gwm_id: str | None = None, metadata: dict | None = None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO entities (campaign_id, label, description, gwm_id, metadata)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb)
            RETURNING *
            """,
            campaign_id, label, description, gwm_id, json.dumps(metadata or {}),
        )
    return _entity_row_to_dict(row)


async def db_bulk_create_entities(campaign_id: str, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $1::uuid, e->>'label', e->>'description', e->>'gwm_id',
                   COALESCE((e->'metadata')::jsonb, '{}'::jsonb)
            FROM jsonb_array_elements($2::jsonb) AS e
            RETURNING *
            """,
            campaign_id, json.dumps(entities),
        )
    return [_entity_row_to_dict(r) for r in rows]


async def db_list_entities(campaign_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM entities WHERE campaign_id = $1::uuid ORDER BY created_at ASC",
            campaign_id,
        )
    return [_entity_row_to_dict(r) for r in rows]


async def db_get_entity(entity_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM entities WHERE id = $1::uuid", entity_id)
    return _entity_row_to_dict(row) if row else None


async def db_delete_entity(entity_id: str, campaign_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM entities WHERE id = $1::uuid AND campaign_id = $2::uuid",
            entity_id, campaign_id,
        )
    return result.endswith("1")


# ── Scout: Attributes ──────────────────────────────────────────────────────────

def _attribute_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_create_attribute(campaign_id: str, label: str, description: str | None = None,
                              weight: float = 1.0) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO attributes (campaign_id, label, description, weight)
            VALUES ($1::uuid, $2, $3, $4)
            RETURNING *
            """,
            campaign_id, label, description, weight,
        )
    return _attribute_row_to_dict(row)


async def db_list_attributes(campaign_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM attributes WHERE campaign_id = $1::uuid ORDER BY created_at ASC",
            campaign_id,
        )
    return [_attribute_row_to_dict(r) for r in rows]


async def db_get_attribute(attribute_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM attributes WHERE id = $1::uuid", attribute_id)
    return _attribute_row_to_dict(row) if row else None


async def db_update_attribute(attribute_id: str, campaign_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    allowed = {"label", "description", "weight"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_attribute(attribute_id)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [attribute_id, campaign_id]
    sql = (
        f"UPDATE attributes SET {', '.join(set_parts)} "
        f"WHERE id = ${len(values)-1}::uuid AND campaign_id = ${len(values)}::uuid RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _attribute_row_to_dict(row) if row else None


async def db_delete_attribute(attribute_id: str, campaign_id: str) -> bool:
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM attributes WHERE id = $1::uuid AND campaign_id = $2::uuid",
            attribute_id, campaign_id,
        )
    return result.endswith("1")


# ── Scout: Validation Jobs ─────────────────────────────────────────────────────

def _job_vrow_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    for ts in ("created_at", "started_at", "completed_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    # Convert UUID arrays to list of strings
    for arr_field in ("entity_filter", "attribute_filter"):
        if arr_field in d and d[arr_field] is not None:
            d[arr_field] = [str(u) for u in d[arr_field]]
    return d


async def db_create_validation_job(campaign_id: str, triggered_by: str,
                                   triggered_sid: str | None = None,
                                   entity_filter: list[str] | None = None,
                                   attribute_filter: list[str] | None = None) -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO validation_jobs
                (campaign_id, triggered_by, triggered_sid, entity_filter, attribute_filter)
            VALUES ($1::uuid, $2, $3, $4::uuid[], $5::uuid[])
            RETURNING *
            """,
            campaign_id, triggered_by, triggered_sid,
            entity_filter or None, attribute_filter or None,
        )
    return _job_vrow_to_dict(row)


async def db_list_validation_jobs(campaign_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM validation_jobs WHERE campaign_id = $1::uuid ORDER BY created_at DESC",
            campaign_id,
        )
    return [_job_vrow_to_dict(r) for r in rows]


async def db_get_validation_job(job_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM validation_jobs WHERE id = $1::uuid", job_id)
    return _job_vrow_to_dict(row) if row else None


async def db_update_validation_job(job_id: str, **kwargs: Any) -> dict[str, Any] | None:
    allowed = {"status", "total_pairs", "completed_pairs", "error", "started_at", "completed_at"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return await db_get_validation_job(job_id)
    set_parts = [f"{k} = ${i+1}" for i, k in enumerate(fields)]
    values = list(fields.values()) + [job_id]
    sql = f"UPDATE validation_jobs SET {', '.join(set_parts)} WHERE id = ${len(values)}::uuid RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _job_vrow_to_dict(row) if row else None


async def db_get_job_details(job_id: str) -> tuple[list[dict], list[dict]]:
    """Return (entities, attributes) for a job, respecting entity/attribute filters."""
    async with _acquire() as conn:
        job = await conn.fetchrow("SELECT * FROM validation_jobs WHERE id = $1::uuid", job_id)
        if not job:
            return [], []
        campaign_id = job["campaign_id"]
        entity_filter = job["entity_filter"]
        attribute_filter = job["attribute_filter"]

        if entity_filter:
            entity_rows = await conn.fetch(
                "SELECT * FROM entities WHERE id = ANY($1::uuid[]) AND campaign_id = $2::uuid",
                entity_filter, campaign_id,
            )
        else:
            entity_rows = await conn.fetch(
                "SELECT * FROM entities WHERE campaign_id = $1::uuid",
                campaign_id,
            )

        if attribute_filter:
            attr_rows = await conn.fetch(
                "SELECT * FROM attributes WHERE id = ANY($1::uuid[]) AND campaign_id = $2::uuid",
                attribute_filter, campaign_id,
            )
        else:
            attr_rows = await conn.fetch(
                "SELECT * FROM attributes WHERE campaign_id = $1::uuid",
                campaign_id,
            )

    entities = [_entity_row_to_dict(r) for r in entity_rows]
    attributes = [_attribute_row_to_dict(r) for r in attr_rows]
    return entities, attributes


async def db_increment_job_progress(job_id: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE validation_jobs SET completed_pairs = completed_pairs + 1 WHERE id = $1::uuid",
            job_id,
        )


# ── Scout: Validation Results ──────────────────────────────────────────────────

def _result_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("id", "job_id", "entity_id", "attribute_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_insert_result(job_id: str, entity_id: str, attribute_id: str,
                           result: dict[str, Any], report_md: str,
                           update_knowledge: bool = True) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO validation_results
                (job_id, entity_id, attribute_id, present, confidence, evidence, report_md)
            VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7)
            ON CONFLICT (job_id, entity_id, attribute_id) DO UPDATE SET
                present = EXCLUDED.present,
                confidence = EXCLUDED.confidence,
                evidence = EXCLUDED.evidence,
                report_md = EXCLUDED.report_md
            """,
            job_id, entity_id, attribute_id,
            result.get("present", False),
            result.get("confidence"),
            result.get("evidence"),
            report_md,
        )
        if update_knowledge:
            await conn.execute(
                """
                INSERT INTO entity_attribute_knowledge
                    (gwm_id, attribute_label, present, confidence, evidence,
                     source_job_id, source_campaign_id, source_campaign_name, entity_label)
                SELECT
                    e.gwm_id,
                    a.label,
                    $4,
                    $5,
                    $6,
                    $1::uuid,
                    j.campaign_id,
                    c.name,
                    e.label
                FROM entities e
                JOIN attributes a ON a.id = $3::uuid
                JOIN validation_jobs j ON j.id = $1::uuid
                JOIN campaigns c ON c.id = j.campaign_id
                WHERE e.id = $2::uuid AND e.gwm_id IS NOT NULL
                ON CONFLICT (gwm_id, attribute_label) DO UPDATE SET
                    present = EXCLUDED.present,
                    confidence = EXCLUDED.confidence,
                    evidence = EXCLUDED.evidence,
                    source_job_id = EXCLUDED.source_job_id,
                    source_campaign_id = EXCLUDED.source_campaign_id,
                    source_campaign_name = EXCLUDED.source_campaign_name,
                    entity_label = EXCLUDED.entity_label,
                    last_updated = NOW()
                """,
                job_id, entity_id, attribute_id,
                result.get("present", False),
                result.get("confidence"),
                result.get("evidence"),
            )


async def db_list_results(job_id: str, entity_id: str | None = None,
                          attribute_id: str | None = None,
                          present: bool | None = None,
                          limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    conditions = ["r.job_id = $1::uuid"]
    values: list[Any] = [job_id]
    idx = 2
    if entity_id:
        conditions.append(f"r.entity_id = ${idx}::uuid")
        values.append(entity_id)
        idx += 1
    if attribute_id:
        conditions.append(f"r.attribute_id = ${idx}::uuid")
        values.append(attribute_id)
        idx += 1
    if present is not None:
        conditions.append(f"r.present = ${idx}")
        values.append(present)
        idx += 1
    values.extend([limit, offset])
    sql = (
        f"SELECT r.*, e.label AS entity_label, a.label AS attribute_label "
        f"FROM validation_results r "
        f"JOIN entities e ON r.entity_id = e.id "
        f"JOIN attributes a ON r.attribute_id = a.id "
        f"WHERE {' AND '.join(conditions)} "
        f"ORDER BY r.created_at DESC LIMIT ${idx} OFFSET ${idx+1}"
    )
    async with _acquire() as conn:
        rows = await conn.fetch(sql, *values)
    return [_result_row_to_dict(r) for r in rows]


# ── Scout: Entity Scores ───────────────────────────────────────────────────────

def _score_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("entity_id", "campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "last_updated" in d and d["last_updated"] is not None:
        d["last_updated"] = d["last_updated"].isoformat()
    return d


async def db_get_scores(campaign_id: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT es.*, e.label AS entity_label, e.gwm_id
            FROM entity_scores es
            JOIN entities e ON es.entity_id = e.id
            WHERE es.campaign_id = $1::uuid
            ORDER BY es.total_score DESC
            """,
            campaign_id,
        )
    return [_score_row_to_dict(r) for r in rows]


async def db_recompute_scores(job_id: str) -> None:
    async with _acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entity_scores
                (entity_id, campaign_id, total_score, attributes_present, attributes_checked, last_updated)
            SELECT
                r.entity_id,
                j.campaign_id,
                SUM(CASE WHEN r.present THEN a.weight ELSE 0 END),
                COUNT(CASE WHEN r.present THEN 1 END),
                COUNT(*),
                NOW()
            FROM validation_results r
            JOIN validation_jobs j ON r.job_id = j.id
            JOIN attributes a ON r.attribute_id = a.id
            WHERE r.job_id = $1::uuid
            GROUP BY r.entity_id, j.campaign_id
            ON CONFLICT (entity_id, campaign_id) DO UPDATE SET
                total_score = EXCLUDED.total_score,
                attributes_present = EXCLUDED.attributes_present,
                attributes_checked = EXCLUDED.attributes_checked,
                last_updated = NOW()
            """,
            job_id,
        )


# ── Scout: Campaign scheduling ─────────────────────────────────────────────────

async def db_get_due_campaigns() -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM campaigns
            WHERE is_active = TRUE
              AND schedule IS NOT NULL
              AND next_run_at <= NOW()
            ORDER BY next_run_at ASC
            """
        )
    return [_campaign_row_to_dict(r) for r in rows]


async def db_update_campaign_next_run(campaign_id: str, next_run_at: Any) -> None:
    async with _acquire() as conn:
        await conn.execute(
            "UPDATE campaigns SET last_run_at = NOW(), next_run_at = $1 WHERE id = $2::uuid",
            next_run_at, campaign_id,
        )


# ── Scout: Global Knowledge Store ─────────────────────────────────────────────

def _knowledge_row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for field in ("source_job_id", "source_campaign_id"):
        if field in d and d[field] is not None:
            d[field] = str(d[field])
    if "last_updated" in d and d["last_updated"] is not None:
        d["last_updated"] = d["last_updated"].isoformat()
    return d


async def db_lookup_knowledge(gwm_id: str, attribute_label: str) -> dict[str, Any] | None:
    """Return cached research result for a gwm_id × attribute_label pair, or None."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM entity_attribute_knowledge WHERE gwm_id = $1 AND attribute_label = $2",
            gwm_id, attribute_label,
        )
    return _knowledge_row_to_dict(row) if row else None


async def db_get_knowledge_for_campaign(campaign_id: str) -> list[dict[str, Any]]:
    """Return all knowledge rows for gwm_id entities in the given campaign."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT k.*
            FROM entity_attribute_knowledge k
            WHERE k.gwm_id IN (
                SELECT gwm_id FROM entities
                WHERE campaign_id = $1::uuid AND gwm_id IS NOT NULL
            )
            ORDER BY k.last_updated DESC
            """,
            campaign_id,
        )
    return [_knowledge_row_to_dict(r) for r in rows]


# ── Scout: Cross-campaign import ───────────────────────────────────────────────

async def db_import_entities(target_campaign_id: str, source_campaign_id: str) -> list[dict[str, Any]]:
    """
    Copy entities from source campaign to target campaign, skipping duplicates.
    Entities with gwm_id: skip if gwm_id already exists in target.
    Entities without gwm_id: skip if label already exists in target.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO entities (campaign_id, label, description, gwm_id, metadata)
            SELECT $2::uuid, label, description, gwm_id, metadata
            FROM entities
            WHERE campaign_id = $1::uuid
              AND (
                (gwm_id IS NOT NULL AND gwm_id NOT IN (
                    SELECT gwm_id FROM entities WHERE campaign_id = $2::uuid AND gwm_id IS NOT NULL))
                OR
                (gwm_id IS NULL AND label NOT IN (
                    SELECT label FROM entities WHERE campaign_id = $2::uuid))
              )
            RETURNING *
            """,
            source_campaign_id, target_campaign_id,
        )
    return [_entity_row_to_dict(r) for r in rows]


async def db_import_attributes(target_campaign_id: str, source_campaign_id: str) -> list[dict[str, Any]]:
    """
    Copy attributes from source campaign to target campaign, skipping label duplicates.
    """
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            INSERT INTO attributes (campaign_id, label, description, weight)
            SELECT $2::uuid, label, description, weight
            FROM attributes
            WHERE campaign_id = $1::uuid
              AND label NOT IN (SELECT label FROM attributes WHERE campaign_id = $2::uuid)
            RETURNING *
            """,
            source_campaign_id, target_campaign_id,
        )
    return [_attribute_row_to_dict(r) for r in rows]


# ── Knowledge Graph ─────────────────────────────────────────────────────────────

async def db_find_or_create_entity(name: str, entity_type: str, aliases: list[str]) -> str:
    """
    Find an existing kg_entity by normalized name or alias, or create a new one.
    Returns the entity UUID as a string.
    """
    normalized = name.lower().strip()
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM kg_entities WHERE LOWER(name) = $1 OR $1 = ANY(aliases)",
            normalized,
        )
        if row:
            entity_id = str(row["id"])
            # Merge any new aliases
            if aliases:
                await conn.execute(
                    "UPDATE kg_entities SET aliases = (SELECT array_agg(DISTINCT a) FROM unnest(aliases || $1::text[]) AS a), updated_at = NOW() WHERE id = $2::uuid",
                    aliases, entity_id,
                )
            return entity_id
        row = await conn.fetchrow(
            """
            INSERT INTO kg_entities (name, entity_type, aliases)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            name.strip(), entity_type, aliases,
        )
        return str(row["id"])


async def db_upsert_relationship(
    subject_id: str,
    predicate: str,
    predicate_family: str,
    object_id: str,
    confidence: float,
    evidence: str | None,
    source_session_id: str | None,
) -> dict[str, Any]:
    """
    Insert a new relationship or detect a conflict with an existing active one.

    Returns a dict with keys: status ("new" | "duplicate" | "conflict"), and
    optionally old_id / new_id for conflicts.
    """
    async with _acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id, predicate FROM kg_relationships
            WHERE subject_id = $1::uuid AND object_id = $2::uuid
              AND predicate_family = $3 AND is_active = TRUE
            """,
            subject_id, object_id, predicate_family,
        )

        if existing is None:
            await conn.execute(
                """
                INSERT INTO kg_relationships
                    (subject_id, predicate, predicate_family, object_id, confidence, evidence, source_session_id)
                VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::uuid)
                """,
                subject_id, predicate, predicate_family, object_id,
                confidence, evidence,
                source_session_id if source_session_id else None,
            )
            return {"status": "new"}

        old_predicate = existing["predicate"]
        old_id = str(existing["id"])

        if old_predicate == predicate:
            return {"status": "duplicate", "old_id": old_id}

        # Conflict: supersede old, insert new, log conflict
        await conn.execute(
            "UPDATE kg_relationships SET is_active = FALSE WHERE id = $1::uuid",
            old_id,
        )
        new_row = await conn.fetchrow(
            """
            INSERT INTO kg_relationships
                (subject_id, predicate, predicate_family, object_id, confidence, evidence, source_session_id)
            VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::uuid)
            RETURNING id
            """,
            subject_id, predicate, predicate_family, object_id,
            confidence, evidence,
            source_session_id if source_session_id else None,
        )
        new_id = str(new_row["id"])

        # Fetch names for conflict log
        subject_row = await conn.fetchrow("SELECT name FROM kg_entities WHERE id = $1::uuid", subject_id)
        object_row = await conn.fetchrow("SELECT name FROM kg_entities WHERE id = $1::uuid", object_id)
        subject_name = subject_row["name"] if subject_row else subject_id
        object_name = object_row["name"] if object_row else object_id

        await conn.execute(
            """
            INSERT INTO kg_relationship_conflicts
                (old_relationship_id, new_relationship_id, old_predicate, new_predicate, subject_name, object_name)
            VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
            """,
            old_id, new_id, old_predicate, predicate, subject_name, object_name,
        )
        return {"status": "conflict", "old_id": old_id, "new_id": new_id}


async def db_get_job_combined_report(job_id: str) -> str:
    """Return all report markdowns for a validation job concatenated together."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.label AS entity_label, a.label AS attribute_label, r.report_md
            FROM validation_results r
            JOIN entities e ON r.entity_id = e.id
            JOIN attributes a ON r.attribute_id = a.id
            WHERE r.job_id = $1::uuid AND r.report_md IS NOT NULL AND r.report_md != ''
            """,
            job_id,
        )
    parts = [
        f"## {row['entity_label']} — {row['attribute_label']}\n\n{row['report_md']}"
        for row in rows
    ]
    return "\n\n---\n\n".join(parts)
