from __future__ import annotations

from ._pool import _acquire


async def init_schema() -> None:
    async with _acquire() as conn:
        # Advisory lock prevents concurrent hot-reload workers from deadlocking
        # on simultaneous ALTER TABLE statements. Lock is session-scoped and
        # released automatically when the connection returns to the pool.
        await conn.execute("SELECT pg_advisory_lock(8675309)")
        try:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS playbook")
            await conn.execute("SET search_path TO playbook, public")
            await conn.execute("""
            -- Users (populated on first SSO login or dev-login)
            CREATE TABLE IF NOT EXISTS playbook.users (
                sid          TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                email        TEXT,
                avatar_url   TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                last_login   TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS playbook.sessions (
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

            ALTER TABLE playbook.users ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT 'dark';

            ALTER TABLE playbook.sessions ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT FALSE;
            ALTER TABLE playbook.sessions ADD COLUMN IF NOT EXISTS usage_tokens INTEGER DEFAULT 0;
            ALTER TABLE playbook.sessions ADD COLUMN IF NOT EXISTS owner_sid TEXT REFERENCES users(sid);
            ALTER TABLE playbook.sessions ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private';
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

            CREATE TABLE IF NOT EXISTS playbook.research_jobs (
                id                UUID PRIMARY KEY,
                query             TEXT NOT NULL,
                webhook_url       TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'queued',
                result_markdown   TEXT NOT NULL DEFAULT '',
                error             TEXT,
                owner_sid         TEXT,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at      TIMESTAMPTZ
            );
            -- backfill: add owner_sid if table already exists
            ALTER TABLE playbook.research_jobs ADD COLUMN IF NOT EXISTS owner_sid TEXT;

            -- Teams
            CREATE TABLE IF NOT EXISTS playbook.teams (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                slug         TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                description  TEXT DEFAULT '',
                created_by   TEXT REFERENCES users(sid),
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );

            -- Team membership with roles
            CREATE TABLE IF NOT EXISTS playbook.team_members (
                team_id   UUID REFERENCES teams(id) ON DELETE CASCADE,
                sid       TEXT REFERENCES users(sid) ON DELETE CASCADE,
                role      TEXT NOT NULL DEFAULT 'member',
                joined_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (team_id, sid)
            );

            -- Session <-> Team sharing
            CREATE TABLE IF NOT EXISTS playbook.session_teams (
                session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                team_id    UUID REFERENCES teams(id) ON DELETE CASCADE,
                shared_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (session_id, team_id)
            );

            -- Comments with @mentions
            CREATE TABLE IF NOT EXISTS playbook.comments (
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
            ALTER TABLE playbook.comments ADD COLUMN IF NOT EXISTS highlight_anchor JSONB;

            -- Pinned sessions per user
            CREATE TABLE IF NOT EXISTS playbook.pinned_sessions (
                sid        TEXT REFERENCES users(sid) ON DELETE CASCADE,
                session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                team_id    UUID REFERENCES teams(id) ON DELETE CASCADE,
                pinned_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (sid, session_id, team_id)
            );

            -- Notifications (polled every 30s)
            CREATE TABLE IF NOT EXISTS playbook.notifications (
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
            CREATE TABLE IF NOT EXISTS playbook.team_activity (
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
            CREATE TABLE IF NOT EXISTS playbook.monitors (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_sid   TEXT NOT NULL,
                label       TEXT NOT NULL,
                query       TEXT NOT NULL,
                frequency   TEXT NOT NULL DEFAULT 'daily',
                is_active   BOOLEAN DEFAULT TRUE,
                last_run_at TIMESTAMPTZ,
                next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            -- migration: add is_active to monitors
            DO $$ BEGIN
                ALTER TABLE playbook.monitors ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
            EXCEPTION WHEN others THEN NULL;
            END $$;

            -- ── Scout: Entity Validation & Scoring Platform ──────────────────

            CREATE TABLE IF NOT EXISTS playbook.campaigns (
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

            CREATE TABLE IF NOT EXISTS playbook.programs (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_sid   TEXT NOT NULL,
                team_id     UUID REFERENCES teams(id) ON DELETE SET NULL,
                name        TEXT NOT NULL,
                description TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS playbook.entities (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                description TEXT,
                gwm_id      TEXT,
                metadata    JSONB DEFAULT '{}',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS entities_campaign_idx ON entities(campaign_id);

            CREATE TABLE IF NOT EXISTS playbook.attributes (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                description TEXT,
                weight      FLOAT DEFAULT 1.0,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS playbook.validation_jobs (
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

            CREATE TABLE IF NOT EXISTS playbook.validation_results (
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

            CREATE TABLE IF NOT EXISTS playbook.entity_scores (
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
            CREATE TABLE IF NOT EXISTS playbook.entity_attribute_knowledge (
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

            CREATE TABLE IF NOT EXISTS playbook.kg_entities (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name        TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                aliases     TEXT[] DEFAULT '{}',
                metadata    JSONB DEFAULT '{}',
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS kg_entities_name_idx ON kg_entities (LOWER(name));

            CREATE TABLE IF NOT EXISTS playbook.kg_relationships (
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

            CREATE TABLE IF NOT EXISTS playbook.kg_relationship_conflicts (
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

            CREATE TABLE IF NOT EXISTS playbook.job_queue (
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

            CREATE INDEX IF NOT EXISTS job_queue_validation_job_idx
                ON job_queue (validation_job_id)
                WHERE validation_job_id IS NOT NULL;

            CREATE TABLE IF NOT EXISTS playbook.attribute_templates (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                owner_sid  TEXT NOT NULL REFERENCES users(sid) ON DELETE CASCADE,
                team_id    UUID REFERENCES teams(id) ON DELETE CASCADE,
                name       TEXT NOT NULL,
                attributes JSONB NOT NULL DEFAULT '[]',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
            # Full-text search on sessions (title + query)
            await conn.execute("""
                ALTER TABLE playbook.sessions ADD COLUMN IF NOT EXISTS search_vec tsvector
                    GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(title,'') || ' ' || coalesce(query,''))
                    ) STORED
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS sessions_search_idx ON sessions USING GIN(search_vec)
            """)
            # Team-scoped campaigns
            await conn.execute("""
                ALTER TABLE playbook.campaigns ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL
            """)
            # ── Migrate unique indexes to case-insensitive + trimmed ─────────
            # Drop old case-sensitive indexes so they can be recreated with
            # LOWER(TRIM(...)) expressions.  Deduplicate any existing rows first
            # so the new unique index creation doesn't fail.
            await conn.execute("""
                DELETE FROM playbook.attributes WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY campaign_id, LOWER(TRIM(label))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.attributes
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("""
                DELETE FROM playbook.entities WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY campaign_id, LOWER(TRIM(label))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.entities
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("""
                DELETE FROM playbook.entities WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY campaign_id, LOWER(TRIM(gwm_id))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.entities
                        WHERE gwm_id IS NOT NULL
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("DROP INDEX IF EXISTS playbook.entities_campaign_label_unique")
            await conn.execute("DROP INDEX IF EXISTS playbook.entities_campaign_gwm_id_unique")
            await conn.execute("DROP INDEX IF EXISTS playbook.attributes_campaign_label_unique")

            # Uniqueness constraints within a campaign (case-insensitive, trimmed)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS entities_campaign_label_unique
                    ON entities (campaign_id, LOWER(TRIM(label)))
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS entities_campaign_gwm_id_unique
                    ON entities (campaign_id, LOWER(TRIM(gwm_id)))
                    WHERE gwm_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS attributes_campaign_label_unique
                    ON attributes (campaign_id, LOWER(TRIM(label)))
            """)
            # ── Collaboration features ──────────────────────────────────────────
            await conn.execute("""
                ALTER TABLE playbook.sessions ADD COLUMN IF NOT EXISTS parent_session_id UUID REFERENCES sessions(id) ON DELETE SET NULL
            """)
            await conn.execute("""
                ALTER TABLE playbook.comments ADD COLUMN IF NOT EXISTS comment_type TEXT NOT NULL DEFAULT 'comment'
            """)
            await conn.execute("""
                ALTER TABLE playbook.comments ADD COLUMN IF NOT EXISTS proposed_text TEXT
            """)
            await conn.execute("""
                ALTER TABLE playbook.comments ADD COLUMN IF NOT EXISTS suggestion_status TEXT DEFAULT 'open'
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.comment_reactions (
                    comment_id UUID REFERENCES comments(id) ON DELETE CASCADE,
                    user_sid   TEXT REFERENCES users(sid)   ON DELETE CASCADE,
                    emoji      TEXT NOT NULL CHECK (emoji IN ('👍','❤️','🔥','💡','✅','❓')),
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (comment_id, user_sid, emoji)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.session_subscriptions (
                    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                    user_sid   TEXT REFERENCES users(sid)   ON DELETE CASCADE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (session_id, user_sid)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.session_presence (
                    session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
                    user_sid   TEXT REFERENCES users(sid)   ON DELETE CASCADE,
                    last_seen  TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (session_id, user_sid)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS session_presence_idx
                    ON session_presence(session_id, last_seen DESC)
            """)
            # ── Global entity / attribute library ───────────────────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.entity_library (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    owner_sid   TEXT NOT NULL REFERENCES users(sid) ON DELETE CASCADE,
                    team_id     UUID REFERENCES teams(id) ON DELETE SET NULL,
                    label       TEXT NOT NULL,
                    description TEXT,
                    gwm_id      TEXT,
                    metadata    JSONB NOT NULL DEFAULT '{}',
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.attribute_library (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    owner_sid   TEXT NOT NULL REFERENCES users(sid) ON DELETE CASCADE,
                    team_id     UUID REFERENCES teams(id) ON DELETE SET NULL,
                    label       TEXT NOT NULL,
                    description TEXT,
                    weight      FLOAT NOT NULL DEFAULT 1.0,
                    created_at  TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            # ── Library uniqueness constraints (case-insensitive, trimmed) ────
            # Deduplicate library tables before adding indexes
            await conn.execute("""
                DELETE FROM playbook.entity_library WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY owner_sid, LOWER(TRIM(label))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.entity_library WHERE team_id IS NULL
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("""
                DELETE FROM playbook.entity_library WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY team_id, LOWER(TRIM(label))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.entity_library WHERE team_id IS NOT NULL
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("""
                DELETE FROM playbook.attribute_library WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY owner_sid, LOWER(TRIM(label))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.attribute_library WHERE team_id IS NULL
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("""
                DELETE FROM playbook.attribute_library WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY team_id, LOWER(TRIM(label))
                            ORDER BY created_at ASC
                        ) AS rn FROM playbook.attribute_library WHERE team_id IS NOT NULL
                    ) sub WHERE rn > 1
                )
            """)
            await conn.execute("DROP INDEX IF EXISTS playbook.entity_library_owner_label_unique")
            await conn.execute("DROP INDEX IF EXISTS playbook.entity_library_team_label_unique")
            await conn.execute("DROP INDEX IF EXISTS playbook.attribute_library_owner_label_unique")
            await conn.execute("DROP INDEX IF EXISTS playbook.attribute_library_team_label_unique")
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS entity_library_owner_label_unique
                    ON entity_library (owner_sid, LOWER(TRIM(label)))
                    WHERE team_id IS NULL
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS entity_library_team_label_unique
                    ON entity_library (team_id, LOWER(TRIM(label)))
                    WHERE team_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS attribute_library_owner_label_unique
                    ON attribute_library (owner_sid, LOWER(TRIM(label)))
                    WHERE team_id IS NULL
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS attribute_library_team_label_unique
                    ON attribute_library (team_id, LOWER(TRIM(label)))
                    WHERE team_id IS NOT NULL
            """)

            # ── Missing FK indexes (prevents slow CASCADE + JOIN scans) ───────
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS validation_results_job_id_idx
                    ON validation_results(job_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS validation_results_attribute_id_idx
                    ON validation_results(attribute_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS attribute_library_owner_idx
                    ON attribute_library(owner_sid)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS attribute_library_team_idx
                    ON attribute_library(team_id) WHERE team_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS entity_library_owner_idx
                    ON entity_library(owner_sid)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS entity_library_team_idx
                    ON entity_library(team_id) WHERE team_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS comments_parent_idx
                    ON comments(parent_id) WHERE parent_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS job_queue_root_job_idx
                    ON job_queue(root_job_id) WHERE root_job_id IS NOT NULL
            """)

            # ── Covering index for DISTINCT ON in export queries ──────────────
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS results_entity_attr_created_idx
                    ON validation_results(entity_id, attribute_id, created_at DESC)
            """)

            # ── Knowledge graph indexes ───────────────────────────────────────
            # object_id index for kg_relationships — the existing unique index
            # has subject_id first, so object_id-only lookups can't use it
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS kg_relationships_object_idx
                    ON kg_relationships(object_id) WHERE is_active = TRUE
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS kg_relationships_subject_idx
                    ON kg_relationships(subject_id) WHERE is_active = TRUE
            """)

            # ── KG Team Scoping ───────────────────────────────────────────
            await conn.execute("""
                ALTER TABLE playbook.kg_entities
                    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL
            """)
            await conn.execute("""
                ALTER TABLE playbook.kg_relationships
                    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL
            """)
            await conn.execute("""
                ALTER TABLE playbook.entity_attribute_knowledge
                    ADD COLUMN IF NOT EXISTS team_id UUID REFERENCES teams(id) ON DELETE SET NULL
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS kg_entities_team_idx
                    ON kg_entities(team_id) WHERE team_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS kg_relationships_team_idx
                    ON kg_relationships(team_id) WHERE team_id IS NOT NULL
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eak_team_idx
                    ON entity_attribute_knowledge(team_id) WHERE team_id IS NOT NULL
            """)

            # ── Campaign lifecycle status ──────────────────────────────────
            await conn.execute("""
                DO $$ BEGIN
                    CREATE TYPE playbook.campaign_status AS ENUM ('draft', 'active', 'completed', 'archived');
                EXCEPTION WHEN duplicate_object THEN NULL;
                END $$
            """)
            await conn.execute("""
                ALTER TABLE playbook.campaigns
                    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'draft'
            """)

            # ── Campaign status audit log ─────────────────────────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.campaign_status_audit (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    old_status      TEXT NOT NULL,
                    new_status      TEXT NOT NULL,
                    changed_by_sid  TEXT NOT NULL,
                    changed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS campaign_status_audit_campaign_idx
                    ON campaign_status_audit(campaign_id, changed_at DESC)
            """)

            # ── Staleness metadata on knowledge cache ─────────────────────
            await conn.execute("""
                ALTER TABLE playbook.entity_attribute_knowledge
                    ADD COLUMN IF NOT EXISTS research_source TEXT DEFAULT 'campaign'
            """)
            await conn.execute("""
                ALTER TABLE playbook.entity_attribute_knowledge
                    ADD COLUMN IF NOT EXISTS research_session_count INT DEFAULT 1
            """)

            # ── Staleness function (STABLE — uses NOW(), per SQL expert rec)
            await conn.execute("""
                CREATE OR REPLACE FUNCTION playbook.compute_staleness_tier(
                    last_updated TIMESTAMPTZ,
                    ref_ts TIMESTAMPTZ DEFAULT NOW()
                )
                RETURNS TEXT AS $$
                BEGIN
                    IF last_updated > ref_ts - INTERVAL '3 days' THEN RETURN 'fresh';
                    ELSIF last_updated > ref_ts - INTERVAL '14 days' THEN RETURN 'warm';
                    ELSIF last_updated > ref_ts - INTERVAL '30 days' THEN RETURN 'stale';
                    ELSE RETURN 'expired';
                    END IF;
                END;
                $$ LANGUAGE plpgsql STABLE
            """)

            # ── Unique constraint for team-scoped knowledge cache
            # (per SQL expert: PK must include team_id scope)
            # Drop old PK and recreate with COALESCE for NULL team_id
            await conn.execute("""
                DO $$
                BEGIN
                    -- Only run if the new unique index doesn't exist yet
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE indexname = 'eak_gwm_attr_team_unique'
                    ) THEN
                        -- Drop old PK if it exists
                        ALTER TABLE playbook.entity_attribute_knowledge
                            DROP CONSTRAINT IF EXISTS entity_attribute_knowledge_pkey;
                        -- Add surrogate PK
                        ALTER TABLE playbook.entity_attribute_knowledge
                            ADD COLUMN IF NOT EXISTS id UUID DEFAULT gen_random_uuid();
                        -- Set id for existing rows
                        UPDATE playbook.entity_attribute_knowledge
                            SET id = gen_random_uuid() WHERE id IS NULL;
                        ALTER TABLE playbook.entity_attribute_knowledge
                            ALTER COLUMN id SET NOT NULL;
                        -- Only add PK if it doesn't exist
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'entity_attribute_knowledge_pkey'
                        ) THEN
                            ALTER TABLE playbook.entity_attribute_knowledge
                                ADD CONSTRAINT entity_attribute_knowledge_pkey PRIMARY KEY (id);
                        END IF;
                        -- New unique index with team_id scope
                        CREATE UNIQUE INDEX eak_gwm_attr_team_unique
                            ON playbook.entity_attribute_knowledge (
                                gwm_id,
                                attribute_label,
                                COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid)
                            );
                    END IF;
                END $$
            """)
            # Partial index for master-only lookups
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eak_master_lookup_idx
                    ON entity_attribute_knowledge(gwm_id, attribute_label)
                    WHERE team_id IS NULL
            """)

            # ── pg_trgm extension for fuzzy entity matching ───────────────
            await conn.execute("""
                CREATE EXTENSION IF NOT EXISTS pg_trgm
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS kg_entities_name_trgm_idx
                    ON kg_entities USING GIN (LOWER(name) gin_trgm_ops)
            """)

            # ── Attribute clusters table ──────────────────────────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.attribute_clusters (
                    id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    campaign_id                UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    cluster_name               TEXT NOT NULL,
                    attribute_ids              UUID[] NOT NULL,
                    research_question_template TEXT NOT NULL,
                    created_at                 TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS attribute_clusters_campaign_idx
                    ON attribute_clusters(campaign_id)
            """)

            # ── KG promotion tracking ─────────────────────────────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.kg_promotions (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    source_team_id  UUID NOT NULL REFERENCES teams(id),
                    entity_id       UUID NOT NULL REFERENCES kg_entities(id),
                    promoted_at     TIMESTAMPTZ DEFAULT NOW(),
                    promoted_by     TEXT DEFAULT 'auto'
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS kg_promotions_entity_idx
                    ON kg_promotions(entity_id)
            """)

            # ── Super admin flag on users ─────────────────────────────────
            await conn.execute("""
                ALTER TABLE playbook.users
                    ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE
            """)

            # ── Disambiguation context for entity deduplication ───────────
            await conn.execute("""
                ALTER TABLE playbook.kg_entities
                    ADD COLUMN IF NOT EXISTS disambiguation_context TEXT DEFAULT ''
            """)
            await conn.execute("""
                ALTER TABLE playbook.kg_entities
                    ADD COLUMN IF NOT EXISTS description TEXT DEFAULT ''
            """)

            # ── Unique constraint scoped by team_id for kg_entities ───────
            await conn.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes
                        WHERE indexname = 'kg_entities_name_team_unique'
                    ) THEN
                        DROP INDEX IF EXISTS playbook.kg_entities_name_idx;
                        CREATE UNIQUE INDEX kg_entities_name_team_unique
                            ON playbook.kg_entities (
                                LOWER(name),
                                COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid)
                            );
                    END IF;
                END $$
            """)

            # ── Persist doc_session_key on sessions ──────────────────────
            await conn.execute("""
                ALTER TABLE playbook.sessions
                    ADD COLUMN IF NOT EXISTS doc_session_key TEXT
            """)

            # ── Dead letter table for failed entity extractions ────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.failed_extraction_tasks (
                    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    session_id      TEXT NOT NULL,
                    msg_id          TEXT NOT NULL,
                    attempt_count   INT NOT NULL DEFAULT 0,
                    last_error      TEXT,
                    team_id         TEXT,
                    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS failed_extraction_session_msg_idx
                    ON failed_extraction_tasks(session_id, msg_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS failed_extraction_session_idx
                    ON failed_extraction_tasks(session_id)
            """)

            # ── External IDs junction table (GWM_ID and other systems) ──────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.entity_external_ids (
                    entity_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    system      TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    created_at  TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (entity_id, system)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS entity_external_ids_system_idx
                    ON entity_external_ids(system, external_id)
            """)

            # ── User Preferences (JSONB) ──────────────────────────────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.user_preferences (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_sid    TEXT NOT NULL REFERENCES users(sid) ON DELETE CASCADE,
                    campaign_id UUID REFERENCES campaigns(id) ON DELETE CASCADE,
                    preferences JSONB NOT NULL DEFAULT '{}',
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS user_preferences_user_campaign_unique
                    ON user_preferences (user_sid, COALESCE(campaign_id, '00000000-0000-0000-0000-000000000000'::uuid))
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS user_preferences_user_idx
                    ON user_preferences(user_sid)
            """)

            # ── Attribute management: type, category, numeric bounds, options ──
            await conn.execute("""
                ALTER TABLE playbook.attributes
                    ADD COLUMN IF NOT EXISTS attribute_type TEXT NOT NULL DEFAULT 'text'
            """)
            await conn.execute("""
                ALTER TABLE playbook.attributes
                    ADD COLUMN IF NOT EXISTS category TEXT
            """)
            await conn.execute("""
                ALTER TABLE playbook.attributes
                    ADD COLUMN IF NOT EXISTS numeric_min FLOAT
            """)
            await conn.execute("""
                ALTER TABLE playbook.attributes
                    ADD COLUMN IF NOT EXISTS numeric_max FLOAT
            """)
            await conn.execute("""
                ALTER TABLE playbook.attributes
                    ADD COLUMN IF NOT EXISTS options JSONB
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS attributes_category_idx
                    ON attributes(campaign_id, category) WHERE category IS NOT NULL
            """)

            # ── Program-Campaign junction ──────────────────────────────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.program_campaigns (
                    program_id  UUID NOT NULL REFERENCES programs(id) ON DELETE CASCADE,
                    campaign_id UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    assigned_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (program_id, campaign_id)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS program_campaigns_campaign_idx
                    ON program_campaigns(campaign_id)
            """)

            # ── Entity-Attribute assignments (matrix cell values) ──────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.entity_attribute_assignments (
                    campaign_id    UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    entity_id      UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    attribute_id   UUID NOT NULL REFERENCES attributes(id) ON DELETE CASCADE,
                    value_boolean  BOOLEAN,
                    value_numeric  FLOAT,
                    value_text     TEXT,
                    value_select   TEXT,
                    updated_at     TIMESTAMPTZ DEFAULT NOW(),
                    updated_by     TEXT,
                    PRIMARY KEY (campaign_id, entity_id, attribute_id)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eaa_entity_idx
                    ON entity_attribute_assignments(entity_id, campaign_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eaa_attribute_idx
                    ON entity_attribute_assignments(attribute_id, campaign_id)
            """)

            # ── Campaign-Attribute assignment (weight overrides) ──────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.campaign_attributes (
                    campaign_id     UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    attribute_id    UUID NOT NULL REFERENCES attributes(id) ON DELETE CASCADE,
                    weight_override FLOAT,
                    display_order   INT NOT NULL DEFAULT 0,
                    assigned_at     TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (campaign_id, attribute_id)
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS campaign_attributes_attr_idx
                    ON campaign_attributes(attribute_id)
            """)

            # ── Metadata schemas (team-scoped field definitions) ──────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.metadata_schemas (
                    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    team_id       UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    field_name    TEXT NOT NULL,
                    field_type    TEXT NOT NULL DEFAULT 'text',
                    label         TEXT NOT NULL,
                    description   TEXT,
                    required      BOOLEAN NOT NULL DEFAULT FALSE,
                    options       JSONB,
                    display_order INT NOT NULL DEFAULT 0,
                    created_at    TIMESTAMPTZ DEFAULT NOW(),
                    updated_at    TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS metadata_schemas_team_field_unique
                    ON metadata_schemas (team_id, LOWER(TRIM(field_name)))
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS metadata_schemas_team_idx
                    ON metadata_schemas(team_id)
            """)

            # ── Score staleness tracking ──────────────────────────────────
            await conn.execute("""
                ALTER TABLE playbook.entity_scores
                    ADD COLUMN IF NOT EXISTS score_stale BOOLEAN NOT NULL DEFAULT FALSE
            """)

            # ── Comparison view function (Section C) ─────────────────────
            # Returns attribute-as-rows, entities-as-columns data for
            # the comparison view. Accepts 2-5 entity UUIDs.
            await conn.execute("""
                CREATE OR REPLACE FUNCTION playbook.comparison_view(
                    p_campaign_id  uuid,
                    p_entity_ids   uuid[]
                )
                RETURNS TABLE (
                    section          text,
                    attribute_id     uuid,
                    attribute_label  text,
                    attribute_type   text,
                    category         text,
                    weight           float,
                    entity_values    jsonb
                ) AS $$
                BEGIN
                    IF array_length(p_entity_ids, 1) < 2
                       OR array_length(p_entity_ids, 1) > 5 THEN
                        RAISE EXCEPTION
                            'Comparison requires 2-5 entities, got %',
                            array_length(p_entity_ids, 1);
                    END IF;

                    RETURN QUERY

                    -- Row 0: Score pseudo-row
                    SELECT
                        'score'::text           AS section,
                        NULL::uuid              AS attribute_id,
                        'Scout Score'::text     AS attribute_label,
                        NULL::text              AS attribute_type,
                        NULL::text              AS category,
                        NULL::float             AS weight,
                        jsonb_object_agg(
                            es.entity_id::text,
                            jsonb_build_object(
                                'total_score', es.total_score,
                                'attributes_present', es.attributes_present,
                                'attributes_checked', es.attributes_checked,
                                'entity_label', e.label
                            )
                        )                       AS entity_values
                    FROM playbook.entity_scores es
                    JOIN playbook.entities e ON e.id = es.entity_id
                    WHERE es.campaign_id = p_campaign_id
                      AND es.entity_id = ANY(p_entity_ids)

                    UNION ALL

                    -- Rows 1..N: one row per attribute
                    SELECT
                        'attribute'::text       AS section,
                        a.id                    AS attribute_id,
                        a.label                 AS attribute_label,
                        a.attribute_type        AS attribute_type,
                        a.category              AS category,
                        a.weight                AS weight,
                        jsonb_object_agg(
                            eid::text,
                            COALESCE(
                                (SELECT jsonb_build_object(
                                    'present', r.present,
                                    'confidence', r.confidence,
                                    'evidence', r.evidence
                                )
                                FROM playbook.validation_results r
                                JOIN playbook.validation_jobs vj ON vj.id = r.job_id
                                WHERE vj.campaign_id = p_campaign_id
                                  AND vj.status = 'done'
                                  AND r.entity_id = eid
                                  AND r.attribute_id = a.id
                                ORDER BY r.created_at DESC
                                LIMIT 1),
                                'null'::jsonb
                            )
                        )                       AS entity_values
                    FROM playbook.attributes a
                    CROSS JOIN unnest(p_entity_ids) AS eid
                    WHERE a.campaign_id = p_campaign_id
                    GROUP BY a.id, a.label, a.attribute_type, a.category, a.weight

                    ORDER BY section DESC, category NULLS LAST, attribute_label;
                END;
                $$ LANGUAGE plpgsql STABLE
            """)

            # ── Entity-attribute value history (audit trail) ──────────
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS playbook.entity_attribute_value_history (
                    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    campaign_id    UUID NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    entity_id      UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                    attribute_id   UUID NOT NULL REFERENCES attributes(id) ON DELETE CASCADE,
                    team_id        UUID REFERENCES teams(id) ON DELETE SET NULL,
                    old_boolean    BOOLEAN,
                    old_numeric    FLOAT,
                    old_text       TEXT,
                    old_select     TEXT,
                    new_boolean    BOOLEAN,
                    new_numeric    FLOAT,
                    new_text       TEXT,
                    new_select     TEXT,
                    changed_by     TEXT,
                    changed_at     TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eavh_campaign_idx
                    ON entity_attribute_value_history(campaign_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eavh_entity_idx
                    ON entity_attribute_value_history(entity_id, campaign_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS eavh_team_idx
                    ON entity_attribute_value_history(team_id)
                    WHERE team_id IS NOT NULL
            """)

            # ── Trigger: capture assignment history on INSERT/UPDATE ───
            await conn.execute("""
                CREATE OR REPLACE FUNCTION playbook.capture_assignment_history()
                RETURNS TRIGGER AS $$
                BEGIN
                    INSERT INTO playbook.entity_attribute_value_history (
                        campaign_id, entity_id, attribute_id, team_id,
                        old_boolean, old_numeric, old_text, old_select,
                        new_boolean, new_numeric, new_text, new_select,
                        changed_by, changed_at
                    ) VALUES (
                        NEW.campaign_id, NEW.entity_id, NEW.attribute_id,
                        (SELECT team_id FROM playbook.campaigns WHERE id = NEW.campaign_id),
                        CASE WHEN TG_OP = 'UPDATE' THEN OLD.value_boolean ELSE NULL END,
                        CASE WHEN TG_OP = 'UPDATE' THEN OLD.value_numeric ELSE NULL END,
                        CASE WHEN TG_OP = 'UPDATE' THEN OLD.value_text ELSE NULL END,
                        CASE WHEN TG_OP = 'UPDATE' THEN OLD.value_select ELSE NULL END,
                        NEW.value_boolean, NEW.value_numeric,
                        NEW.value_text, NEW.value_select,
                        NEW.updated_by, NOW()
                    );
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
            """)
            await conn.execute("""
                DROP TRIGGER IF EXISTS trg_capture_assignment_history
                    ON playbook.entity_attribute_assignments
            """)
            await conn.execute("""
                CREATE TRIGGER trg_capture_assignment_history
                    AFTER INSERT OR UPDATE ON playbook.entity_attribute_assignments
                    FOR EACH ROW EXECUTE FUNCTION playbook.capture_assignment_history()
            """)

            # ── Row-Level Security policies ────────────────────────────
            # RLS on campaigns: users see own campaigns or campaigns
            # belonging to teams they're members of.
            await conn.execute("""
                ALTER TABLE playbook.campaigns ENABLE ROW LEVEL SECURITY
            """)
            await conn.execute("""
                DROP POLICY IF EXISTS campaigns_team_isolation ON playbook.campaigns
            """)
            await conn.execute("""
                CREATE POLICY campaigns_team_isolation ON playbook.campaigns
                    USING (
                        team_id IS NULL
                        OR team_id::text = current_setting('app.current_team_id', true)
                    )
            """)

            # RLS on entities: scoped through campaign
            await conn.execute("""
                ALTER TABLE playbook.entities ENABLE ROW LEVEL SECURITY
            """)
            await conn.execute("""
                DROP POLICY IF EXISTS entities_team_isolation ON playbook.entities
            """)
            await conn.execute("""
                CREATE POLICY entities_team_isolation ON playbook.entities
                    USING (
                        campaign_id IN (
                            SELECT id FROM playbook.campaigns
                            WHERE team_id IS NULL
                               OR team_id::text = current_setting('app.current_team_id', true)
                        )
                    )
            """)

            # RLS on entity_attribute_assignments
            await conn.execute("""
                ALTER TABLE playbook.entity_attribute_assignments
                    ENABLE ROW LEVEL SECURITY
            """)
            await conn.execute("""
                DROP POLICY IF EXISTS eaa_team_isolation
                    ON playbook.entity_attribute_assignments
            """)
            await conn.execute("""
                CREATE POLICY eaa_team_isolation
                    ON playbook.entity_attribute_assignments
                    USING (
                        campaign_id IN (
                            SELECT id FROM playbook.campaigns
                            WHERE team_id IS NULL
                               OR team_id::text = current_setting('app.current_team_id', true)
                        )
                    )
            """)

            # RLS on entity_scores
            await conn.execute("""
                ALTER TABLE playbook.entity_scores ENABLE ROW LEVEL SECURITY
            """)
            await conn.execute("""
                DROP POLICY IF EXISTS scores_team_isolation ON playbook.entity_scores
            """)
            await conn.execute("""
                CREATE POLICY scores_team_isolation ON playbook.entity_scores
                    USING (
                        campaign_id IN (
                            SELECT id FROM playbook.campaigns
                            WHERE team_id IS NULL
                               OR team_id::text = current_setting('app.current_team_id', true)
                        )
                    )
            """)

            # RLS on entity_attribute_value_history
            await conn.execute("""
                ALTER TABLE playbook.entity_attribute_value_history
                    ENABLE ROW LEVEL SECURITY
            """)
            await conn.execute("""
                DROP POLICY IF EXISTS eavh_team_isolation
                    ON playbook.entity_attribute_value_history
            """)
            await conn.execute("""
                CREATE POLICY eavh_team_isolation
                    ON playbook.entity_attribute_value_history
                    USING (
                        team_id IS NULL
                        OR team_id::text = current_setting('app.current_team_id', true)
                    )
            """)

            # RLS on validation_jobs
            await conn.execute("""
                ALTER TABLE playbook.validation_jobs ENABLE ROW LEVEL SECURITY
            """)
            await conn.execute("""
                DROP POLICY IF EXISTS vjobs_team_isolation
                    ON playbook.validation_jobs
            """)
            await conn.execute("""
                CREATE POLICY vjobs_team_isolation ON playbook.validation_jobs
                    USING (
                        campaign_id IN (
                            SELECT id FROM playbook.campaigns
                            WHERE team_id IS NULL
                               OR team_id::text = current_setting('app.current_team_id', true)
                        )
                    )
            """)

            # Pool connections are superuser/owner — exempt from RLS by default.
            # RLS is enforced when SET LOCAL app.current_team_id is set via
            # _acquire_team(). Non-team queries use _acquire() which bypasses RLS
            # (table owner is exempt). This is intentional: admin/system queries
            # need full access, while user-facing team queries get isolation.

        finally:
            await conn.execute("SELECT pg_advisory_unlock(8675309)")
