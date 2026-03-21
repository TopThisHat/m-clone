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
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                completed_at      TIMESTAMPTZ
            );

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

        finally:
            await conn.execute("SELECT pg_advisory_unlock(8675309)")
