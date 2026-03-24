from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _kg_entity_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    for uid in ("team_id",):
        if uid in d and d[uid] is not None:
            d[uid] = str(d[uid])
    for ts in ("created_at", "updated_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    # Normalize nullable array/object columns
    if d.get("aliases") is None:
        d["aliases"] = []
    if d.get("metadata") is None:
        d["metadata"] = {}
    return d


def _kg_rel_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for f in ("id", "subject_id", "object_id", "source_session_id", "team_id"):
        if f in d and d[f] is not None:
            d[f] = str(d[f])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


# ── Entity CRUD ──────────────────────────────────────────────────────────────

async def db_find_or_create_entity(
    name: str,
    entity_type: str,
    aliases: list[str],
    team_id: str | None = None,
    disambiguation_context: str = "",
) -> str:
    """
    Find an existing kg_entity by normalized name or alias, or create a new one.
    Returns the entity UUID as a string.

    When disambiguation_context is provided (e.g. "CEO of Acme Corp"), it is
    compared against existing entities with the same name to decide whether to
    create a new record or merge with an existing one.

    Searches within the given team scope + master graph (team_id IS NULL).
    Uses INSERT ... ON CONFLICT to avoid race conditions when concurrent
    extraction workers process the same entity simultaneously.
    """
    normalized = name.lower().strip()
    async with _acquire() as conn:
        # Build team-scope condition for searches
        if team_id:
            team_cond = "(team_id = $2::uuid OR team_id IS NULL)"
            alias_args: list[Any] = [normalized, team_id]
        else:
            team_cond = "team_id IS NULL"
            alias_args = [normalized]

        # Check aliases first (can't be handled by ON CONFLICT)
        row = await conn.fetchrow(
            f"SELECT id, disambiguation_context FROM playbook.kg_entities WHERE $1 = ANY(aliases) AND {team_cond}",
            *alias_args,
        )
        if row:
            existing_ctx = row["disambiguation_context"] or ""
            # If disambiguation context suggests a different person, skip alias match
            if disambiguation_context and existing_ctx and _contexts_conflict(disambiguation_context, existing_ctx):
                pass  # Fall through to create new entity
            else:
                entity_id = str(row["id"])
                updates = ["aliases = (SELECT array_agg(DISTINCT a) FROM unnest(aliases || $1::text[]) AS a)", "updated_at = NOW()"]
                update_args: list[Any] = [aliases or []]
                if disambiguation_context and not existing_ctx:
                    updates.append(f"disambiguation_context = ${len(update_args) + 1}")
                    update_args.append(disambiguation_context)
                update_args.append(entity_id)
                await conn.execute(
                    f"UPDATE playbook.kg_entities SET {', '.join(updates)} WHERE id = ${len(update_args)}::uuid",
                    *update_args,
                )
                return entity_id

        # Atomic upsert by name — handles concurrent inserts safely
        # Use team-scoped unique constraint
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id, disambiguation_context)
            VALUES ($1, $2, $3, $4::uuid, $5)
            ON CONFLICT (LOWER(name), COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid)) DO UPDATE SET
                aliases = (SELECT array_agg(DISTINCT a)
                           FROM unnest(playbook.kg_entities.aliases || EXCLUDED.aliases) AS a),
                disambiguation_context = CASE
                    WHEN playbook.kg_entities.disambiguation_context = '' AND EXCLUDED.disambiguation_context != ''
                    THEN EXCLUDED.disambiguation_context
                    ELSE playbook.kg_entities.disambiguation_context
                END,
                updated_at = NOW()
            RETURNING id
            """,
            name.strip(), entity_type, aliases or [], team_id, disambiguation_context or "",
        )
        return str(row["id"])


def _contexts_conflict(ctx_a: str, ctx_b: str) -> bool:
    """Heuristic check if two disambiguation contexts refer to different entities."""
    a_lower = ctx_a.lower()
    b_lower = ctx_b.lower()
    # If both have company/org context and they differ, likely different people
    a_orgs = {w for w in a_lower.split() if len(w) > 3}
    b_orgs = {w for w in b_lower.split() if len(w) > 3}
    if a_orgs and b_orgs and not a_orgs & b_orgs:
        return True
    return False


async def db_find_similar_entities(
    name: str,
    team_id: str | None = None,
    threshold: float = 0.3,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Find KG entities similar to `name` using pg_trgm.
    Searches within team scope + master graph.
    Returns list of {id, name, entity_type, aliases, similarity} sorted by similarity DESC.
    """
    async with _acquire() as conn:
        # Set the similarity threshold for the % operator
        await conn.execute(f"SET pg_trgm.similarity_threshold = {threshold}")
        rows = await conn.fetch(
            """
            SELECT id, name, entity_type, aliases, metadata, disambiguation_context, description,
                   similarity(LOWER(name), LOWER($1)) AS similarity
            FROM playbook.kg_entities
            WHERE LOWER(name) % LOWER($1)
              AND (team_id = $2::uuid OR team_id IS NULL)
            ORDER BY similarity DESC
            LIMIT $3
            """,
            name, team_id, limit,
        )
    return [_kg_entity_to_dict(r) for r in rows]


async def db_merge_kg_entities(keep_id: str, merge_id: str) -> None:
    """
    Merge entity merge_id into keep_id:
    - Move all relationships from merge_id to keep_id
    - Merge aliases (include merge_id's name as alias)
    - Delete merge_id
    """
    async with _acquire() as conn:
        async with conn.transaction():
            merge_row = await conn.fetchrow(
                "SELECT name, aliases FROM playbook.kg_entities WHERE id = $1::uuid",
                merge_id,
            )
            if merge_row is None:
                return

            await conn.execute(
                "UPDATE playbook.kg_relationships SET subject_id = $1::uuid WHERE subject_id = $2::uuid",
                keep_id, merge_id,
            )
            await conn.execute(
                "UPDATE playbook.kg_relationships SET object_id = $1::uuid WHERE object_id = $2::uuid",
                keep_id, merge_id,
            )

            merge_aliases = list(merge_row["aliases"] or [])
            merge_aliases.append(merge_row["name"])
            await conn.execute(
                """
                UPDATE playbook.kg_entities
                SET aliases = (SELECT array_agg(DISTINCT a) FROM unnest(aliases || $1::text[]) AS a),
                    updated_at = NOW()
                WHERE id = $2::uuid
                """,
                merge_aliases, keep_id,
            )
            await conn.execute("DELETE FROM playbook.kg_entities WHERE id = $1::uuid", merge_id)


async def db_update_kg_entity(
    entity_id: str,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    """Update an entity's editable fields. Returns updated entity or None."""
    allowed = {"name", "entity_type", "aliases", "metadata", "description", "disambiguation_context"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return await db_get_kg_entity(entity_id)
    set_parts = []
    values: list[Any] = []
    for i, (k, v) in enumerate(fields.items(), 1):
        if k == "aliases":
            set_parts.append(f"aliases = ${i}::text[]")
        elif k == "metadata":
            set_parts.append(f"metadata = ${i}::jsonb")
        else:
            set_parts.append(f"{k} = ${i}")
        values.append(v)
    set_parts.append(f"updated_at = NOW()")
    values.append(entity_id)
    sql = f"UPDATE playbook.kg_entities SET {', '.join(set_parts)} WHERE id = ${len(values)}::uuid RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _kg_entity_to_dict(row) if row else None


async def db_delete_kg_entity(entity_id: str) -> bool:
    """Delete an entity and cascade-delete its relationships."""
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.kg_entities WHERE id = $1::uuid", entity_id
        )
    return result.endswith("1")


async def db_update_kg_relationship(
    rel_id: str,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    """Update a relationship's editable fields."""
    allowed = {"predicate", "predicate_family", "confidence", "evidence"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return None
    set_parts = []
    values: list[Any] = []
    for i, (k, v) in enumerate(fields.items(), 1):
        set_parts.append(f"{k} = ${i}")
        values.append(v)
    values.append(rel_id)
    sql = f"UPDATE playbook.kg_relationships SET {', '.join(set_parts)} WHERE id = ${len(values)}::uuid RETURNING *"
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _kg_rel_to_dict(row) if row else None


async def db_get_kg_relationship(rel_id: str) -> dict[str, Any] | None:
    """Fetch a single relationship by ID."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM playbook.kg_relationships WHERE id = $1::uuid", rel_id
        )
    return _kg_rel_to_dict(row) if row else None


async def db_delete_kg_relationship(rel_id: str) -> bool:
    """Delete a relationship."""
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.kg_relationships WHERE id = $1::uuid", rel_id
        )
    return result.endswith("1")


# ── Relationship upsert ──────────────────────────────────────────────────────

async def db_upsert_relationship(
    subject_id: str,
    predicate: str,
    predicate_family: str,
    object_id: str,
    confidence: float,
    evidence: str | None,
    source_session_id: str | None,
    team_id: str | None = None,
) -> dict[str, Any]:
    """
    Insert a new relationship or detect a conflict with an existing active one.

    Uses SELECT FOR UPDATE inside a transaction to prevent race conditions
    when concurrent extraction workers process overlapping relationships.

    Returns a dict with keys: status ("new" | "duplicate" | "conflict"), and
    optionally old_id / new_id for conflicts.
    """
    async with _acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                """
                SELECT id, predicate FROM playbook.kg_relationships
                WHERE subject_id = $1::uuid AND object_id = $2::uuid
                  AND predicate_family = $3 AND is_active = TRUE
                FOR UPDATE
                """,
                subject_id, object_id, predicate_family,
            )

            if existing is None:
                try:
                    await conn.execute(
                        """
                        INSERT INTO playbook.kg_relationships
                            (subject_id, predicate, predicate_family, object_id, confidence, evidence, source_session_id, team_id)
                        VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::uuid, $8::uuid)
                        """,
                        subject_id, predicate, predicate_family, object_id,
                        confidence, evidence,
                        source_session_id if source_session_id else None,
                        team_id,
                    )
                    return {"status": "new"}
                except asyncpg.UniqueViolationError:
                    return {"status": "duplicate"}

            old_predicate = existing["predicate"]
            old_id = str(existing["id"])

            if old_predicate == predicate:
                return {"status": "duplicate", "old_id": old_id}

            # Conflict: supersede old, insert new, log conflict
            await conn.execute(
                "UPDATE playbook.kg_relationships SET is_active = FALSE WHERE id = $1::uuid",
                old_id,
            )
            new_row = await conn.fetchrow(
                """
                INSERT INTO playbook.kg_relationships
                    (subject_id, predicate, predicate_family, object_id, confidence, evidence, source_session_id, team_id)
                VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::uuid, $8::uuid)
                RETURNING id
                """,
                subject_id, predicate, predicate_family, object_id,
                confidence, evidence,
                source_session_id if source_session_id else None,
                team_id,
            )
            new_id = str(new_row["id"])

            subject_row = await conn.fetchrow("SELECT name FROM playbook.kg_entities WHERE id = $1::uuid", subject_id)
            object_row = await conn.fetchrow("SELECT name FROM playbook.kg_entities WHERE id = $1::uuid", object_id)
            subject_name = subject_row["name"] if subject_row else subject_id
            object_name = object_row["name"] if object_row else object_id

            await conn.execute(
                """
                INSERT INTO playbook.kg_relationship_conflicts
                    (old_relationship_id, new_relationship_id, old_predicate, new_predicate, subject_name, object_name)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6)
                """,
                old_id, new_id, old_predicate, predicate, subject_name, object_name,
            )
            return {"status": "conflict", "old_id": old_id, "new_id": new_id}


# ── List / Search / Stats ────────────────────────────────────────────────────

async def db_list_kg_entities(
    search: str | None = None,
    entity_type: str | None = None,
    team_id: str | None = None,
    include_master: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    conditions = []
    args: list[Any] = []
    idx = 0
    if search:
        idx += 1
        conditions.append(f"(LOWER(e.name) LIKE ${idx} OR LOWER(e.description) LIKE ${idx})")
        args.append(f"%{search.lower()}%")
    if entity_type:
        idx += 1
        conditions.append(f"e.entity_type = ${idx}")
        args.append(entity_type)
    if team_id:
        idx += 1
        if include_master:
            conditions.append(f"(e.team_id = ${idx}::uuid OR e.team_id IS NULL)")
        else:
            conditions.append(f"e.team_id = ${idx}::uuid")
        args.append(team_id)
    elif not include_master:
        # No team and not super admin — should not happen (router blocks it)
        conditions.append("FALSE")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    idx += 1
    limit_param = f"${idx}"
    args.append(limit)
    idx += 1
    offset_param = f"${idx}"
    args.append(offset)
    async with _acquire() as conn:
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*)::int AS total FROM playbook.kg_entities e{where}", *args[:-2]
        )
        total = count_row["total"] if count_row else 0
        rows = await conn.fetch(
            f"""
            SELECT e.*,
                   COALESCE(rc.cnt, 0)::int AS relationship_count
            FROM playbook.kg_entities e
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships
                ) sub GROUP BY entity_id
            ) rc ON rc.entity_id = e.id
            {where}
            ORDER BY e.updated_at DESC
            LIMIT {limit_param} OFFSET {offset_param}
            """,
            *args,
        )
    return {"items": [_kg_entity_to_dict(r) for r in rows], "total": total}


async def db_get_kg_entity(entity_id: str) -> dict[str, Any] | None:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM playbook.kg_entities WHERE id = $1::uuid", entity_id
        )
    return _kg_entity_to_dict(row) if row else None


async def db_get_entity_relationships(
    entity_id: str,
    direction: str = "both",
    team_id: str | None = None,
    include_master: bool = False,
) -> list[dict[str, Any]]:
    conditions = []
    args: list[Any] = [entity_id]
    if direction == "outgoing":
        conditions.append("r.subject_id = $1::uuid")
    elif direction == "incoming":
        conditions.append("r.object_id = $1::uuid")
    else:
        conditions.append("(r.subject_id = $1::uuid OR r.object_id = $1::uuid)")
    conditions.append("r.is_active = TRUE")
    if team_id:
        idx = len(args) + 1
        if include_master:
            conditions.append(f"(r.team_id = ${idx}::uuid OR r.team_id IS NULL)")
        else:
            conditions.append(f"r.team_id = ${idx}::uuid")
        args.append(team_id)
    elif not include_master:
        # No team and not super admin — restrict to nothing
        conditions.append("FALSE")
    where = " AND ".join(conditions)
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT r.*,
                   s.name AS subject_name, s.entity_type AS subject_type,
                   o.name AS object_name, o.entity_type AS object_type
            FROM playbook.kg_relationships r
            JOIN playbook.kg_entities s ON s.id = r.subject_id
            JOIN playbook.kg_entities o ON o.id = r.object_id
            WHERE {where}
            ORDER BY r.created_at DESC
            """,
            *args,
        )
    return [_kg_rel_to_dict(r) for r in rows]


async def db_search_kg(
    query: str,
    team_id: str | None = None,
    include_master: bool = False,
) -> list[dict[str, Any]]:
    conditions = [
        "(LOWER(e.name) LIKE $1 OR $2 = ANY(SELECT LOWER(a) FROM unnest(e.aliases) a) OR LOWER(e.description) LIKE $1)"
    ]
    args: list[Any] = [f"%{query.lower()}%", query.lower()]
    idx = 2
    if team_id:
        idx += 1
        if include_master:
            conditions.append(f"(e.team_id = ${idx}::uuid OR e.team_id IS NULL)")
        else:
            conditions.append(f"e.team_id = ${idx}::uuid")
        args.append(team_id)
    elif not include_master:
        conditions.append("FALSE")
    where = " AND ".join(conditions)
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT e.*,
                   COALESCE(rc.cnt, 0)::int AS relationship_count
            FROM playbook.kg_entities e
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships
                ) sub GROUP BY entity_id
            ) rc ON rc.entity_id = e.id
            WHERE {where}
            ORDER BY e.updated_at DESC LIMIT 50
            """,
            *args,
        )
    return [_kg_entity_to_dict(r) for r in rows]


async def db_get_kg_stats(team_id: str | None = None, include_master: bool = False) -> dict[str, Any]:
    if team_id:
        if include_master:
            team_cond_e = "WHERE (team_id = $1::uuid OR team_id IS NULL)"
            team_cond_r = "WHERE is_active = TRUE AND (team_id = $1::uuid OR team_id IS NULL)"
        else:
            team_cond_e = "WHERE team_id = $1::uuid"
            team_cond_r = "WHERE is_active = TRUE AND team_id = $1::uuid"
        args: list[Any] = [team_id]
    elif include_master:
        team_cond_e = ""
        team_cond_r = "WHERE is_active = TRUE"
        args = []
    else:
        team_cond_e = "WHERE FALSE"
        team_cond_r = "WHERE FALSE"
        args = []
    async with _acquire() as conn:
        if args:
            row = await conn.fetchrow(
                f"""
                SELECT
                    (SELECT COUNT(*)::int FROM playbook.kg_entities {team_cond_e}) AS total_entities,
                    (SELECT COUNT(*)::int FROM playbook.kg_relationships {team_cond_r}) AS total_relationships,
                    (SELECT COUNT(*)::int FROM playbook.kg_relationship_conflicts) AS total_conflicts,
                    (SELECT COUNT(DISTINCT entity_type)::int FROM playbook.kg_entities {team_cond_e}) AS entity_types
                """,
                *args,
            )
        else:
            row = await conn.fetchrow(
                f"""
                SELECT
                    (SELECT COUNT(*)::int FROM playbook.kg_entities) AS total_entities,
                    (SELECT COUNT(*)::int FROM playbook.kg_relationships WHERE is_active = TRUE) AS total_relationships,
                    (SELECT COUNT(*)::int FROM playbook.kg_relationship_conflicts) AS total_conflicts,
                    (SELECT COUNT(DISTINCT entity_type)::int FROM playbook.kg_entities) AS entity_types
                """
            )
    return dict(row) if row else {"total_entities": 0, "total_relationships": 0, "total_conflicts": 0, "entity_types": 0}


async def db_list_kg_conflicts(
    limit: int = 50,
    offset: int = 0,
    team_id: str | None = None,
    include_master: bool = False,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    args: list[Any] = []
    idx = 0
    if team_id:
        idx += 1
        if include_master:
            conditions.append(f"(nr.team_id = ${idx}::uuid OR nr.team_id IS NULL)")
        else:
            conditions.append(f"nr.team_id = ${idx}::uuid")
        args.append(team_id)
    elif not include_master:
        conditions.append("FALSE")
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    idx += 1
    args.append(limit)
    idx += 1
    args.append(offset)
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT c.*, c.subject_name, c.object_name
            FROM playbook.kg_relationship_conflicts c
            JOIN playbook.kg_relationships nr ON nr.id = c.new_relationship_id
            {where}
            ORDER BY c.detected_at DESC
            LIMIT ${idx - 1} OFFSET ${idx}
            """,
            *args,
        )
    result = []
    for r in rows:
        d = dict(r)
        for f in ("id", "old_relationship_id", "new_relationship_id"):
            if f in d and d[f] is not None:
                d[f] = str(d[f])
        if "detected_at" in d and d["detected_at"] is not None:
            d["detected_at"] = d["detected_at"].isoformat()
        result.append(d)
    return result


# ── KG Graph / Deal-Partners ────────────────────────────────────────────────

async def db_get_kg_graph(
    entity_types: list[str] | None = None,
    predicate_families: list[str] | None = None,
    team_id: str | None = None,
    include_master: bool = False,
    search: str | None = None,
    metadata_key: str | None = None,
    metadata_value: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return nodes + edges for the D3 force-directed graph explorer."""
    conditions = ["r.is_active = TRUE"]
    args: list[Any] = []
    idx = 0
    if entity_types:
        idx += 1
        conditions.append(f"(s.entity_type = ANY(${idx}::text[]) OR o.entity_type = ANY(${idx}::text[]))")
        args.append(entity_types)
    if predicate_families:
        idx += 1
        conditions.append(f"r.predicate_family = ANY(${idx}::text[])")
        args.append(predicate_families)
    if team_id:
        idx += 1
        if include_master:
            conditions.append(f"(r.team_id = ${idx}::uuid OR r.team_id IS NULL)")
        else:
            conditions.append(f"r.team_id = ${idx}::uuid")
        args.append(team_id)
    elif not include_master:
        conditions.append("FALSE")
    if search:
        idx += 1
        search_like = f"%{search.lower()}%"
        conditions.append(
            f"(LOWER(s.name) LIKE ${idx} OR LOWER(o.name) LIKE ${idx} "
            f"OR LOWER(s.description) LIKE ${idx} OR LOWER(o.description) LIKE ${idx} "
            f"OR ${idx} = ANY(SELECT LOWER(a) FROM unnest(s.aliases) a) "
            f"OR ${idx} = ANY(SELECT LOWER(a) FROM unnest(o.aliases) a))"
        )
        args.append(search_like)
    if metadata_key and metadata_value:
        idx += 1
        meta_k = metadata_key
        idx += 1
        conditions.append(
            f"(s.metadata->>'{meta_k}' ILIKE ${idx} OR o.metadata->>'{meta_k}' ILIKE ${idx})"
        )
        args.append(f"%{metadata_value}%")
    elif metadata_key:
        conditions.append(
            f"(s.metadata ? '{metadata_key}' OR o.metadata ? '{metadata_key}')"
        )
    where = " AND ".join(conditions)
    idx += 1
    args.append(limit)
    async with _acquire() as conn:
        # When a limit is applied, prioritize relationships involving the
        # most-connected entities so the graph visualization shows the most
        # important nodes first.
        rows = await conn.fetch(
            f"""
            SELECT r.id, r.subject_id, r.object_id, r.predicate, r.predicate_family, r.confidence, r.team_id,
                   s.name AS subject_name, s.entity_type AS subject_type, s.aliases AS subject_aliases,
                   s.description AS subject_description, s.metadata AS subject_metadata,
                   o.name AS object_name, o.entity_type AS object_type, o.aliases AS object_aliases,
                   o.description AS object_description, o.metadata AS object_metadata
            FROM playbook.kg_relationships r
            JOIN playbook.kg_entities s ON s.id = r.subject_id
            JOIN playbook.kg_entities o ON o.id = r.object_id
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                ) sub GROUP BY entity_id
            ) src ON src.entity_id = r.subject_id
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                ) sub GROUP BY entity_id
            ) trc ON trc.entity_id = r.object_id
            WHERE {where}
            ORDER BY GREATEST(COALESCE(src.cnt, 0), COALESCE(trc.cnt, 0)) DESC, r.created_at DESC
            LIMIT ${idx}
            """,
            *args,
        )
    # Build unique node set from edges
    node_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for r in rows:
        sid = str(r["subject_id"])
        oid = str(r["object_id"])
        if sid not in node_map:
            node_map[sid] = {
                "id": sid, "name": r["subject_name"], "entity_type": r["subject_type"],
                "aliases": list(r["subject_aliases"]) if isinstance(r["subject_aliases"], list) else [],
                "description": r["subject_description"] or "",
                "metadata": r["subject_metadata"] if isinstance(r["subject_metadata"], dict) else {},
            }
        if oid not in node_map:
            node_map[oid] = {
                "id": oid, "name": r["object_name"], "entity_type": r["object_type"],
                "aliases": list(r["object_aliases"]) if isinstance(r["object_aliases"], list) else [],
                "description": r["object_description"] or "",
                "metadata": r["object_metadata"] if isinstance(r["object_metadata"], dict) else {},
            }
        edge_source = "team" if r["team_id"] else "master"
        edges.append({
            "id": str(r["id"]),
            "source": sid,
            "target": oid,
            "predicate": r["predicate"],
            "predicate_family": r["predicate_family"],
            "confidence": float(r["confidence"]),
            "graph_source": edge_source,
        })
    return {"nodes": list(node_map.values()), "edges": edges}


async def db_get_deal_partners(
    team_id: str | None = None,
    include_master: bool = False,
) -> list[dict[str, Any]]:
    """Find pairs of persons connected to the same entity via transaction relationships."""
    team_cond = ""
    args: list[Any] = []
    if team_id:
        if include_master:
            team_cond = " AND (r.team_id = $1::uuid OR r.team_id IS NULL)"
        else:
            team_cond = " AND r.team_id = $1::uuid"
        args.append(team_id)
    elif not include_master:
        team_cond = " AND FALSE"
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            WITH person_deals AS (
                SELECT r.subject_id AS person_id, pe.name AS person_name,
                       r.object_id AS deal_entity_id, de.name AS deal_entity_name,
                       r.predicate
                FROM playbook.kg_relationships r
                JOIN playbook.kg_entities pe ON pe.id = r.subject_id AND pe.entity_type = 'person'
                JOIN playbook.kg_entities de ON de.id = r.object_id
                WHERE r.predicate_family = 'transaction' AND r.is_active = TRUE
                {team_cond}
            )
            SELECT a.person_id AS person1_id, a.person_name AS person1_name,
                   b.person_id AS person2_id, b.person_name AS person2_name,
                   a.deal_entity_id, a.deal_entity_name,
                   a.predicate AS person1_predicate, b.predicate AS person2_predicate
            FROM person_deals a
            JOIN person_deals b ON a.deal_entity_id = b.deal_entity_id AND a.person_id < b.person_id
            ORDER BY a.person_name, b.person_name
            """,
            *args,
        )
    groups: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = f"{r['person1_id']}:{r['person2_id']}"
        if key not in groups:
            groups[key] = {
                "person1": {"id": str(r["person1_id"]), "name": r["person1_name"]},
                "person2": {"id": str(r["person2_id"]), "name": r["person2_name"]},
                "shared_deals": [],
            }
        groups[key]["shared_deals"].append({
            "entity_id": str(r["deal_entity_id"]),
            "entity_name": r["deal_entity_name"],
            "person1_predicate": r["person1_predicate"],
            "person2_predicate": r["person2_predicate"],
        })
    return list(groups.values())


# ── KG Query (for agent tool) ───────────────────────────────────────────────

async def db_query_kg(
    query: str,
    team_id: str | None = None,
    include_master: bool = False,
) -> dict[str, Any]:
    """
    Search the knowledge graph for entities and relationships matching a query.
    Only searches master graph if include_master is True (super admin).
    Returns results with source attribution (master vs team).
    """
    search_pattern = f"%{query.lower()}%"
    results: dict[str, Any] = {"entities": [], "relationships": [], "sources_used": []}

    async with _acquire() as conn:
        # Search entities in master graph only if super admin
        if include_master:
            master_entities = await conn.fetch(
                """
                SELECT e.*, 'master' AS graph_source,
                       COALESCE(rc.cnt, 0)::int AS relationship_count
                FROM playbook.kg_entities e
                LEFT JOIN (
                    SELECT entity_id, COUNT(*) AS cnt FROM (
                        SELECT subject_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                        UNION ALL
                        SELECT object_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                    ) sub GROUP BY entity_id
                ) rc ON rc.entity_id = e.id
                WHERE e.team_id IS NULL
                  AND (LOWER(e.name) LIKE $1
                       OR $2 = ANY(SELECT LOWER(a) FROM unnest(e.aliases) a)
                       OR LOWER(e.description) LIKE $1)
                ORDER BY e.updated_at DESC
                LIMIT 20
                """,
                search_pattern, query.lower(),
            )
            if master_entities:
                results["sources_used"].append("master")
                for r in master_entities:
                    d = _kg_entity_to_dict(r)
                    d["graph_source"] = "master"
                    results["entities"].append(d)

        # Search team graph if team_id provided
        if team_id:
            team_entities = await conn.fetch(
                """
                SELECT e.*, 'team' AS graph_source,
                       COALESCE(rc.cnt, 0)::int AS relationship_count
                FROM playbook.kg_entities e
                LEFT JOIN (
                    SELECT entity_id, COUNT(*) AS cnt FROM (
                        SELECT subject_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                        UNION ALL
                        SELECT object_id AS entity_id FROM playbook.kg_relationships WHERE is_active = TRUE
                    ) sub GROUP BY entity_id
                ) rc ON rc.entity_id = e.id
                WHERE e.team_id = $1::uuid
                  AND (LOWER(e.name) LIKE $2
                       OR $3 = ANY(SELECT LOWER(a) FROM unnest(e.aliases) a)
                       OR LOWER(e.description) LIKE $2)
                ORDER BY e.updated_at DESC
                LIMIT 20
                """,
                team_id, search_pattern, query.lower(),
            )
            if team_entities:
                results["sources_used"].append("team")
                for r in team_entities:
                    d = _kg_entity_to_dict(r)
                    d["graph_source"] = "team"
                    results["entities"].append(d)

        # Get relationships for found entities
        entity_ids = [e["id"] for e in results["entities"]]
        if entity_ids:
            rels = await conn.fetch(
                """
                SELECT r.*,
                       s.name AS subject_name, s.entity_type AS subject_type,
                       o.name AS object_name, o.entity_type AS object_type,
                       CASE WHEN r.team_id IS NULL THEN 'master' ELSE 'team' END AS graph_source
                FROM playbook.kg_relationships r
                JOIN playbook.kg_entities s ON s.id = r.subject_id
                JOIN playbook.kg_entities o ON o.id = r.object_id
                WHERE r.is_active = TRUE
                  AND (r.subject_id = ANY($1::uuid[]) OR r.object_id = ANY($1::uuid[]))
                ORDER BY r.confidence DESC, r.created_at DESC
                LIMIT 50
                """,
                entity_ids,
            )
            for r in rels:
                d = _kg_rel_to_dict(r)
                d["graph_source"] = r["graph_source"]
                d["subject_name"] = r["subject_name"]
                d["object_name"] = r["object_name"]
                results["relationships"].append(d)

    return results


# ── Neighborhood expansion ────────────────────────────────────────────────

async def db_get_neighbors(
    entity_id: str,
    *,
    depth: int = 1,
    limit: int = 50,
    exclude_ids: list[str] | None = None,
    team_id: str | None = None,
    include_master: bool = False,
) -> dict[str, Any]:
    """Return neighboring nodes and edges for progressive graph expansion.

    Uses a recursive CTE to traverse relationships up to *depth* hops.
    Returns ``{"nodes": [...], "edges": [...]}``.
    """
    depth = max(1, min(depth, 3))  # Clamp to 1-3
    limit = max(1, min(limit, 200))

    exclude = exclude_ids or []

    # Build team scope condition
    team_cond = ""
    args: list[Any] = [entity_id, depth, limit, exclude]
    if team_id:
        if include_master:
            team_cond = "AND (r.team_id = $5::uuid OR r.team_id IS NULL)"
        else:
            team_cond = "AND r.team_id = $5::uuid"
        args.append(team_id)
    elif not include_master:
        team_cond = "AND FALSE"

    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            WITH RECURSIVE neighbors AS (
                -- Base case: direct relationships from the seed entity
                SELECT r.id AS rel_id,
                       r.subject_id, r.object_id,
                       r.predicate, r.predicate_family, r.confidence, r.team_id,
                       CASE WHEN r.subject_id = $1::uuid THEN r.object_id ELSE r.subject_id END AS neighbor_id,
                       1 AS hop
                FROM playbook.kg_relationships r
                WHERE r.is_active = TRUE
                  AND (r.subject_id = $1::uuid OR r.object_id = $1::uuid)
                  {team_cond}

                UNION ALL

                -- Recursive case: follow edges from discovered neighbors
                SELECT r.id,
                       r.subject_id, r.object_id,
                       r.predicate, r.predicate_family, r.confidence, r.team_id,
                       CASE WHEN r.subject_id = n.neighbor_id THEN r.object_id ELSE r.subject_id END,
                       n.hop + 1
                FROM playbook.kg_relationships r
                JOIN neighbors n ON (r.subject_id = n.neighbor_id OR r.object_id = n.neighbor_id)
                WHERE r.is_active = TRUE
                  AND n.hop < $2
                  AND r.id != n.rel_id
                  {team_cond}
            )
            SELECT DISTINCT ON (n.rel_id)
                n.rel_id, n.subject_id, n.object_id,
                n.predicate, n.predicate_family, n.confidence, n.team_id,
                n.hop,
                s.name AS subject_name, s.entity_type AS subject_type,
                s.aliases AS subject_aliases, s.description AS subject_description,
                s.metadata AS subject_metadata,
                o.name AS object_name, o.entity_type AS object_type,
                o.aliases AS object_aliases, o.description AS object_description,
                o.metadata AS object_metadata
            FROM neighbors n
            JOIN playbook.kg_entities s ON s.id = n.subject_id
            JOIN playbook.kg_entities o ON o.id = n.object_id
            WHERE n.neighbor_id != ALL($4::uuid[])
            ORDER BY n.rel_id, n.hop
            LIMIT $3
            """,
            *args,
        )

    node_map: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for r in rows:
        sid = str(r["subject_id"])
        oid = str(r["object_id"])
        if sid not in node_map:
            node_map[sid] = {
                "id": sid, "name": r["subject_name"], "entity_type": r["subject_type"],
                "aliases": list(r["subject_aliases"]) if isinstance(r["subject_aliases"], list) else [],
                "description": r["subject_description"] or "",
                "metadata": r["subject_metadata"] if isinstance(r["subject_metadata"], dict) else {},
            }
        if oid not in node_map:
            node_map[oid] = {
                "id": oid, "name": r["object_name"], "entity_type": r["object_type"],
                "aliases": list(r["object_aliases"]) if isinstance(r["object_aliases"], list) else [],
                "description": r["object_description"] or "",
                "metadata": r["object_metadata"] if isinstance(r["object_metadata"], dict) else {},
            }
        edge_source = "team" if r["team_id"] else "master"
        edges.append({
            "id": str(r["rel_id"]),
            "source": sid,
            "target": oid,
            "predicate": r["predicate"],
            "predicate_family": r["predicate_family"],
            "confidence": float(r["confidence"]),
            "graph_source": edge_source,
            "hop": r["hop"],
        })
    return {"nodes": list(node_map.values()), "edges": edges}
