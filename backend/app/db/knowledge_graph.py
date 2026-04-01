from __future__ import annotations

from typing import Any

import asyncpg

from ..config import settings
from ._pool import _acquire


def _kg_entity_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    for uid in ("team_id", "master_entity_id"):
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
    team_id: str,
    disambiguation_context: str = "",
) -> tuple[str, str]:
    """Find or create a kg_entity using 4-phase resolution.

    Resolution order:
      1. **team_hit** — exact name match within team scope.
      2. **team_alias_hit** — alias match within team scope.
      3. **master_copy** — name match in master team, copy to team.
      4. **created** — brand-new entity in the team.

    Returns ``(entity_id, resolution_mode)`` where *resolution_mode* is one of
    ``"team_hit"``, ``"team_alias_hit"``, ``"master_copy"``, or ``"created"``.
    """
    normalized = name.lower().strip()
    async with _acquire() as conn:
        # Phase 1: exact name match within team
        row = await conn.fetchrow(
            "SELECT id FROM playbook.kg_entities "
            "WHERE LOWER(name) = $1 AND team_id = $2::uuid",
            normalized, team_id,
        )
        if row:
            entity_id = str(row["id"])
            # Merge aliases + update disambiguation if absent
            await _merge_aliases(conn, entity_id, aliases, disambiguation_context)
            return entity_id, "team_hit"

        # Phase 2: alias match within team
        row = await conn.fetchrow(
            "SELECT id, disambiguation_context FROM playbook.kg_entities "
            "WHERE $1 = ANY(aliases) AND team_id = $2::uuid",
            normalized, team_id,
        )
        if row:
            existing_ctx = row["disambiguation_context"] or ""
            if disambiguation_context and existing_ctx and _contexts_conflict(disambiguation_context, existing_ctx):
                pass  # Fall through — contexts conflict, create new
            else:
                entity_id = str(row["id"])
                await _merge_aliases(conn, entity_id, aliases, disambiguation_context)
                return entity_id, "team_alias_hit"

        # Phase 3: name match in master team → copy to team
        master_row = await conn.fetchrow(
            "SELECT id, name, entity_type, aliases, description, disambiguation_context, metadata "
            "FROM playbook.kg_entities "
            "WHERE LOWER(name) = $1 AND team_id = $2::uuid",
            normalized, settings.kg_master_team_id,
        )
        if master_row:
            master_id = str(master_row["id"])
            master_aliases = list(master_row["aliases"]) if master_row["aliases"] else []
            combined_aliases = list({a for a in (master_aliases + (aliases or [])) if a})
            new_row = await conn.fetchrow(
                """
                INSERT INTO playbook.kg_entities
                    (name, entity_type, aliases, team_id, description,
                     disambiguation_context, metadata, master_entity_id)
                VALUES ($1, $2, $3, $4::uuid, $5, $6, $7::jsonb, $8::uuid)
                ON CONFLICT (LOWER(name), team_id) DO UPDATE SET
                    aliases = (SELECT array_agg(DISTINCT a)
                               FROM unnest(playbook.kg_entities.aliases || EXCLUDED.aliases) AS a),
                    updated_at = NOW()
                RETURNING id
                """,
                master_row["name"],
                master_row["entity_type"],
                combined_aliases,
                team_id,
                master_row["description"] or "",
                master_row["disambiguation_context"] or disambiguation_context or "",
                master_row["metadata"] if master_row["metadata"] else {},
                master_id,
            )
            return str(new_row["id"]), "master_copy"

        # Phase 4: create new entity in team
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_entities (name, entity_type, aliases, team_id, disambiguation_context)
            VALUES ($1, $2, $3, $4::uuid, $5)
            ON CONFLICT (LOWER(name), team_id) DO UPDATE SET
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
        return str(row["id"]), "created"


async def _merge_aliases(
    conn: asyncpg.Connection,
    entity_id: str,
    aliases: list[str],
    disambiguation_context: str,
) -> None:
    """Merge new aliases into an existing entity, optionally filling disambiguation."""
    updates = [
        "aliases = (SELECT array_agg(DISTINCT a) FROM unnest(aliases || $1::text[]) AS a)",
        "updated_at = NOW()",
    ]
    args: list[Any] = [aliases or []]
    if disambiguation_context:
        updates.append(
            f"disambiguation_context = COALESCE(NULLIF(disambiguation_context, ''), ${len(args) + 1})"
        )
        args.append(disambiguation_context)
    args.append(entity_id)
    await conn.execute(
        f"UPDATE playbook.kg_entities SET {', '.join(updates)} WHERE id = ${len(args)}::uuid",
        *args,
    )


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


# ── Entity flag / review operations ─────────────────────────────────────────

async def db_flag_entity_for_review(
    entity_id: str,
    team_id: str,
    reason: str,
) -> dict[str, Any] | None:
    """Insert a review flag for an entity.  ON CONFLICT DO NOTHING (unique on entity_id+team_id+reason).

    Returns the flag row as a dict, or ``None`` if it already exists.
    """
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_entity_flags (entity_id, team_id, reason)
            VALUES ($1::uuid, $2::uuid, $3)
            ON CONFLICT (entity_id, team_id, reason) DO NOTHING
            RETURNING *
            """,
            entity_id, team_id, reason,
        )
    if row is None:
        return None
    d = dict(row)
    for uid in ("id", "entity_id", "team_id"):
        if uid in d and d[uid] is not None:
            d[uid] = str(d[uid])
    for ts in ("created_at", "resolved_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


async def db_list_entity_flags(team_id: str) -> list[dict[str, Any]]:
    """List unresolved entity flags for a team, joined with entity name/type."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT f.*, e.name AS entity_name, e.entity_type
            FROM playbook.kg_entity_flags f
            JOIN playbook.kg_entities e ON e.id = f.entity_id
            WHERE f.team_id = $1::uuid AND f.resolved = FALSE
            ORDER BY f.created_at DESC
            """,
            team_id,
        )
    result = []
    for r in rows:
        d = dict(r)
        for uid in ("id", "entity_id", "team_id"):
            if uid in d and d[uid] is not None:
                d[uid] = str(d[uid])
        for ts in ("created_at", "resolved_at"):
            if ts in d and d[ts] is not None:
                d[ts] = d[ts].isoformat()
        result.append(d)
    return result


async def db_resolve_entity_flag(flag_id: str, resolved_by: str) -> bool:
    """Mark a flag as resolved.  Returns True if the flag was found and updated."""
    async with _acquire() as conn:
        result = await conn.execute(
            """
            UPDATE playbook.kg_entity_flags
            SET resolved = TRUE, resolved_by = $2, resolved_at = NOW()
            WHERE id = $1::uuid
            """,
            flag_id, resolved_by,
        )
    return result.endswith("1")


# ── Similar entities ────────────────────────────────────────────────────────

async def db_find_similar_entities(
    name: str,
    team_id: str,
    threshold: float = 0.3,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find KG entities similar to *name* using pg_trgm within team scope only.

    Returns list of ``{id, name, entity_type, aliases, similarity}`` sorted by
    similarity DESC.
    """
    if not (0.0 < threshold < 1.0):
        raise ValueError(f"threshold must be between 0 and 1 exclusive, got {threshold}")
    safe_threshold = float(threshold)
    async with _acquire() as conn:
        await conn.execute(
            "SET pg_trgm.similarity_threshold = " + str(safe_threshold)
        )
        rows = await conn.fetch(
            """
            SELECT id, name, entity_type, aliases, metadata, disambiguation_context, description,
                   similarity(LOWER(name), LOWER($1)) AS similarity
            FROM playbook.kg_entities
            WHERE LOWER(name) % LOWER($1)
              AND team_id = $2::uuid
            ORDER BY similarity DESC
            LIMIT $3
            """,
            name, team_id, limit,
        )
    return [_kg_entity_to_dict(r) for r in rows]


# ── Entity update / delete ──────────────────────────────────────────────────

async def db_update_kg_entity(
    entity_id: str,
    patch: dict[str, Any],
    team_id: str,
) -> dict[str, Any] | None:
    """Update an entity's editable fields.  Returns updated entity or None."""
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
    set_parts.append("updated_at = NOW()")
    values.append(entity_id)
    values.append(team_id)
    sql = (
        f"UPDATE playbook.kg_entities SET {', '.join(set_parts)} "
        f"WHERE id = ${len(values) - 1}::uuid AND team_id = ${len(values)}::uuid "
        "RETURNING *"
    )
    async with _acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    return _kg_entity_to_dict(row) if row else None


async def db_delete_kg_entity(entity_id: str, team_id: str) -> bool:
    """Delete an entity and cascade-delete its relationships.  Team-scoped."""
    async with _acquire() as conn:
        result = await conn.execute(
            "DELETE FROM playbook.kg_entities WHERE id = $1::uuid AND team_id = $2::uuid",
            entity_id, team_id,
        )
    return result.endswith("1")


# ── Relationship update / delete (unchanged team scoping) ───────────────────

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
    """Insert a new relationship or detect a conflict with an existing active one.

    Uses SELECT FOR UPDATE inside a transaction to prevent race conditions
    when concurrent extraction workers process overlapping relationships.

    The SELECT now includes ``AND team_id = $N::uuid`` so that concurrent
    teams cannot collide.

    Catches ``asyncpg.CheckViolationError`` on INSERT and returns
    ``{"status": "cross_team_error"}`` when a cross-team FK violation occurs.

    Returns a dict with keys: status ("new" | "duplicate" | "conflict" |
    "cross_team_error"), and optionally old_id / new_id for conflicts.
    """
    async with _acquire() as conn:
        async with conn.transaction():
            # Task 4.5: team_id added to the FOR UPDATE check
            existing = await conn.fetchrow(
                """
                SELECT id, predicate FROM playbook.kg_relationships
                WHERE subject_id = $1::uuid AND object_id = $2::uuid
                  AND predicate_family = $3 AND is_active = TRUE
                  AND team_id = $4::uuid
                FOR UPDATE
                """,
                subject_id, object_id, predicate_family, team_id,
            )

            if existing is None:
                try:
                    await conn.execute(
                        """
                        INSERT INTO playbook.kg_relationships
                            (subject_id, predicate, predicate_family, object_id,
                             confidence, evidence, source_session_id, team_id)
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
                except asyncpg.CheckViolationError:
                    # Task 4.6: cross-team FK violation
                    return {"status": "cross_team_error"}

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
                    (subject_id, predicate, predicate_family, object_id,
                     confidence, evidence, source_session_id, team_id)
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
                    (old_relationship_id, new_relationship_id, old_predicate, new_predicate,
                     subject_name, object_name, team_id)
                VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid)
                """,
                old_id, new_id, old_predicate, predicate, subject_name, object_name, team_id,
            )
            return {"status": "conflict", "old_id": old_id, "new_id": new_id}


# ── List / Search / Stats ────────────────────────────────────────────────────

async def db_list_kg_entities(
    search: str | None = None,
    entity_type: str | None = None,
    team_id: str = "",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List KG entities scoped to a single team.  ``team_id`` is REQUIRED."""
    conditions = []
    args: list[Any] = []
    idx = 0

    # Team scope is mandatory
    idx += 1
    conditions.append(f"e.team_id = ${idx}::uuid")
    args.append(team_id)

    if search:
        idx += 1
        conditions.append(f"(LOWER(e.name) LIKE ${idx} OR LOWER(e.description) LIKE ${idx})")
        args.append(f"%{search.lower()}%")
    if entity_type:
        idx += 1
        conditions.append(f"e.entity_type = ${idx}")
        args.append(entity_type)

    where = " WHERE " + " AND ".join(conditions)
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
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships WHERE team_id = $1::uuid
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships WHERE team_id = $1::uuid
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
    team_id: str = "",
) -> list[dict[str, Any]]:
    """Get relationships for an entity, scoped to a single team."""
    conditions = []
    args: list[Any] = [entity_id]
    if direction == "outgoing":
        conditions.append("r.subject_id = $1::uuid")
    elif direction == "incoming":
        conditions.append("r.object_id = $1::uuid")
    else:
        conditions.append("(r.subject_id = $1::uuid OR r.object_id = $1::uuid)")
    conditions.append("r.is_active = TRUE")

    idx = len(args) + 1
    conditions.append(f"r.team_id = ${idx}::uuid")
    args.append(team_id)

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
    team_id: str,
) -> list[dict[str, Any]]:
    """Search KG entities by name, alias, or description within a single team."""
    conditions = [
        "(LOWER(e.name) LIKE $1 OR $2 = ANY(SELECT LOWER(a) FROM unnest(e.aliases) a) OR LOWER(e.description) LIKE $1)"
    ]
    args: list[Any] = [f"%{query.lower()}%", query.lower()]

    idx = 3
    conditions.append(f"e.team_id = ${idx}::uuid")
    args.append(team_id)

    where = " AND ".join(conditions)
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT e.*,
                   COALESCE(rc.cnt, 0)::int AS relationship_count
            FROM playbook.kg_entities e
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships WHERE team_id = $3::uuid
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships WHERE team_id = $3::uuid
                ) sub GROUP BY entity_id
            ) rc ON rc.entity_id = e.id
            WHERE {where}
            ORDER BY e.updated_at DESC LIMIT 50
            """,
            *args,
        )
    return [_kg_entity_to_dict(r) for r in rows]


async def db_get_kg_stats(team_id: str) -> dict[str, Any]:
    """Get aggregate KG statistics for a single team."""
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*)::int FROM playbook.kg_entities WHERE team_id = $1::uuid) AS total_entities,
                (SELECT COUNT(*)::int FROM playbook.kg_relationships
                 WHERE is_active = TRUE AND team_id = $1::uuid) AS total_relationships,
                (SELECT COUNT(*)::int FROM playbook.kg_relationship_conflicts
                 WHERE team_id = $1::uuid) AS total_conflicts,
                (SELECT COUNT(DISTINCT entity_type)::int FROM playbook.kg_entities
                 WHERE team_id = $1::uuid) AS entity_types
            """,
            team_id,
        )
    return dict(row) if row else {
        "total_entities": 0, "total_relationships": 0, "total_conflicts": 0, "entity_types": 0,
    }


async def db_list_kg_conflicts(
    limit: int = 50,
    offset: int = 0,
    team_id: str = "",
) -> list[dict[str, Any]]:
    """List relationship conflicts for a team.

    Uses ``c.team_id`` directly (the conflicts table now has a team_id column).
    """
    args: list[Any] = [team_id, limit, offset]
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.*, c.subject_name, c.object_name
            FROM playbook.kg_relationship_conflicts c
            WHERE c.team_id = $1::uuid
            ORDER BY c.detected_at DESC
            LIMIT $2 OFFSET $3
            """,
            *args,
        )
    result = []
    for r in rows:
        d = dict(r)
        for f in ("id", "old_relationship_id", "new_relationship_id", "team_id"):
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
    team_id: str = "",
    search: str | None = None,
    metadata_key: str | None = None,
    metadata_value: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return nodes + edges for the D3 force-directed graph explorer.  Team-scoped."""
    conditions = ["r.is_active = TRUE"]
    args: list[Any] = []
    idx = 0

    # Team scope is mandatory
    idx += 1
    conditions.append(f"r.team_id = ${idx}::uuid")
    args.append(team_id)

    if entity_types:
        idx += 1
        conditions.append(f"(s.entity_type = ANY(${idx}::text[]) OR o.entity_type = ANY(${idx}::text[]))")
        args.append(entity_types)
    if predicate_families:
        idx += 1
        conditions.append(f"r.predicate_family = ANY(${idx}::text[])")
        args.append(predicate_families)
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
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships
                    WHERE is_active = TRUE AND team_id = $1::uuid
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships
                    WHERE is_active = TRUE AND team_id = $1::uuid
                ) sub GROUP BY entity_id
            ) src ON src.entity_id = r.subject_id
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships
                    WHERE is_active = TRUE AND team_id = $1::uuid
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships
                    WHERE is_active = TRUE AND team_id = $1::uuid
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
        edges.append({
            "id": str(r["id"]),
            "source": sid,
            "target": oid,
            "predicate": r["predicate"],
            "predicate_family": r["predicate_family"],
            "confidence": float(r["confidence"]),
        })
    return {"nodes": list(node_map.values()), "edges": edges}


async def db_get_deal_partners(
    team_id: str,
) -> list[dict[str, Any]]:
    """Find pairs of persons connected to the same entity via transaction relationships.  Team-scoped."""
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            WITH person_deals AS (
                SELECT r.subject_id AS person_id, pe.name AS person_name,
                       r.object_id AS deal_entity_id, de.name AS deal_entity_name,
                       r.predicate
                FROM playbook.kg_relationships r
                JOIN playbook.kg_entities pe ON pe.id = r.subject_id AND pe.entity_type = 'person'
                JOIN playbook.kg_entities de ON de.id = r.object_id
                WHERE r.predicate_family = 'transaction' AND r.is_active = TRUE
                  AND r.team_id = $1::uuid
            )
            SELECT a.person_id AS person1_id, a.person_name AS person1_name,
                   b.person_id AS person2_id, b.person_name AS person2_name,
                   a.deal_entity_id, a.deal_entity_name,
                   a.predicate AS person1_predicate, b.predicate AS person2_predicate
            FROM person_deals a
            JOIN person_deals b ON a.deal_entity_id = b.deal_entity_id AND a.person_id < b.person_id
            ORDER BY a.person_name, b.person_name
            """,
            team_id,
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
    team_id: str,
) -> dict[str, Any]:
    """Search the knowledge graph for entities and relationships matching a query.

    Strictly team-scoped.  To query the master graph, pass
    ``settings.kg_master_team_id`` as *team_id*.
    """
    search_pattern = f"%{query.lower()}%"
    results: dict[str, Any] = {"entities": [], "relationships": [], "sources_used": []}

    async with _acquire() as conn:
        team_entities = await conn.fetch(
            """
            SELECT e.*, 'team' AS graph_source,
                   COALESCE(rc.cnt, 0)::int AS relationship_count
            FROM playbook.kg_entities e
            LEFT JOIN (
                SELECT entity_id, COUNT(*) AS cnt FROM (
                    SELECT subject_id AS entity_id FROM playbook.kg_relationships
                    WHERE is_active = TRUE AND team_id = $1::uuid
                    UNION ALL
                    SELECT object_id AS entity_id FROM playbook.kg_relationships
                    WHERE is_active = TRUE AND team_id = $1::uuid
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
                       'team' AS graph_source
                FROM playbook.kg_relationships r
                JOIN playbook.kg_entities s ON s.id = r.subject_id
                JOIN playbook.kg_entities o ON o.id = r.object_id
                WHERE r.is_active = TRUE
                  AND r.team_id = $1::uuid
                  AND (r.subject_id = ANY($2::uuid[]) OR r.object_id = ANY($2::uuid[]))
                ORDER BY r.confidence DESC, r.created_at DESC
                LIMIT 50
                """,
                team_id, entity_ids,
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
    team_id: str = "",
) -> dict[str, Any]:
    """Return neighboring nodes and edges for progressive graph expansion.

    Uses a recursive CTE to traverse relationships up to *depth* hops.
    Returns ``{"nodes": [...], "edges": [...]}``.  Team-scoped.
    """
    depth = max(1, min(depth, 3))  # Clamp to 1-3
    limit = max(1, min(limit, 200))

    exclude = exclude_ids or []
    args: list[Any] = [entity_id, depth, limit, exclude, team_id]

    async with _acquire() as conn:
        rows = await conn.fetch(
            """
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
                  AND r.team_id = $5::uuid

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
                  AND r.team_id = $5::uuid
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
        edges.append({
            "id": str(r["rel_id"]),
            "source": sid,
            "target": oid,
            "predicate": r["predicate"],
            "predicate_family": r["predicate_family"],
            "confidence": float(r["confidence"]),
            "hop": r["hop"],
        })
    return {"nodes": list(node_map.values()), "edges": edges}


# ── Master promotion / sync ─────────────────────────────────────────────────

async def db_promote_entity_to_master(entity_id: str, team_id: str) -> str | None:
    """Promote a team entity to the master knowledge graph.

    1. Verify entity belongs to *team_id*.
    2. Create or update a master entity (INSERT ON CONFLICT with master team_id).
    3. Set the team entity's ``master_entity_id`` to the master entity id.
    4. Return the master entity id, or ``None`` if the entity was not found.
    """
    master_team_id = settings.kg_master_team_id
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM playbook.kg_entities WHERE id = $1::uuid AND team_id = $2::uuid",
            entity_id, team_id,
        )
        if row is None:
            return None

        master_row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_entities
                (name, entity_type, aliases, team_id, description,
                 disambiguation_context, metadata)
            VALUES ($1, $2, $3, $4::uuid, $5, $6, $7::jsonb)
            ON CONFLICT (LOWER(name), team_id) DO UPDATE SET
                aliases = (SELECT array_agg(DISTINCT a)
                           FROM unnest(playbook.kg_entities.aliases || EXCLUDED.aliases) AS a),
                description = COALESCE(NULLIF(EXCLUDED.description, ''), playbook.kg_entities.description),
                metadata = playbook.kg_entities.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
            """,
            row["name"],
            row["entity_type"],
            list(row["aliases"]) if row["aliases"] else [],
            master_team_id,
            row["description"] or "",
            row["disambiguation_context"] or "",
            row["metadata"] if row["metadata"] else {},
        )
        master_id = str(master_row["id"])

        await conn.execute(
            "UPDATE playbook.kg_entities SET master_entity_id = $1::uuid, updated_at = NOW() "
            "WHERE id = $2::uuid",
            master_id, entity_id,
        )
        return master_id


async def db_sync_entity_from_master(entity_id: str, team_id: str) -> dict[str, Any] | None:
    """Sync a team entity from its master entity.

    Copies name, entity_type, aliases, description from the master entity
    to the team entity.  Returns the updated team entity dict, or ``None``
    if the entity has no ``master_entity_id``.
    """
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, master_entity_id FROM playbook.kg_entities "
            "WHERE id = $1::uuid AND team_id = $2::uuid",
            entity_id, team_id,
        )
        if row is None or row["master_entity_id"] is None:
            return None

        master_row = await conn.fetchrow(
            "SELECT name, entity_type, aliases, description FROM playbook.kg_entities WHERE id = $1::uuid",
            str(row["master_entity_id"]),
        )
        if master_row is None:
            return None

        updated = await conn.fetchrow(
            """
            UPDATE playbook.kg_entities SET
                name = $1,
                entity_type = $2,
                aliases = $3,
                description = $4,
                updated_at = NOW()
            WHERE id = $5::uuid AND team_id = $6::uuid
            RETURNING *
            """,
            master_row["name"],
            master_row["entity_type"],
            list(master_row["aliases"]) if master_row["aliases"] else [],
            master_row["description"] or "",
            entity_id,
            team_id,
        )
    return _kg_entity_to_dict(updated) if updated else None


# ── Entity merge ────────────────────────────────────────────────────────────

async def db_merge_kg_entities(
    winner_id: str,
    loser_id: str,
    team_id: str,
) -> dict[str, Any] | None:
    """Merge *loser* entity into *winner* entity within the same team.

    1. Verify both entities belong to *team_id*.
    2. Re-point all relationships from loser to winner.
    3. Append loser's name to winner's aliases.
    4. Delete the loser entity.
    5. Return the updated winner entity.
    """
    async with _acquire() as conn:
        async with conn.transaction():
            winner_row = await conn.fetchrow(
                "SELECT id, name, aliases FROM playbook.kg_entities "
                "WHERE id = $1::uuid AND team_id = $2::uuid FOR UPDATE",
                winner_id, team_id,
            )
            loser_row = await conn.fetchrow(
                "SELECT id, name, aliases FROM playbook.kg_entities "
                "WHERE id = $1::uuid AND team_id = $2::uuid FOR UPDATE",
                loser_id, team_id,
            )
            if winner_row is None or loser_row is None:
                return None

            # Re-point relationships where loser is subject
            await conn.execute(
                "UPDATE playbook.kg_relationships SET subject_id = $1::uuid "
                "WHERE subject_id = $2::uuid AND team_id = $3::uuid",
                winner_id, loser_id, team_id,
            )
            # Re-point relationships where loser is object
            await conn.execute(
                "UPDATE playbook.kg_relationships SET object_id = $1::uuid "
                "WHERE object_id = $2::uuid AND team_id = $3::uuid",
                winner_id, loser_id, team_id,
            )

            # Append loser's name to winner's aliases
            loser_name = loser_row["name"]
            loser_aliases = list(loser_row["aliases"]) if loser_row["aliases"] else []
            new_aliases = list({loser_name} | set(loser_aliases))

            updated = await conn.fetchrow(
                """
                UPDATE playbook.kg_entities SET
                    aliases = (SELECT array_agg(DISTINCT a)
                               FROM unnest(aliases || $1::text[]) AS a),
                    updated_at = NOW()
                WHERE id = $2::uuid
                RETURNING *
                """,
                new_aliases, winner_id,
            )

            # Delete the loser entity
            await conn.execute(
                "DELETE FROM playbook.kg_entities WHERE id = $1::uuid AND team_id = $2::uuid",
                loser_id, team_id,
            )

    return _kg_entity_to_dict(updated) if updated else None
