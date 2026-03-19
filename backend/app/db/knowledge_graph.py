from __future__ import annotations

from typing import Any

import asyncpg

from ._pool import _acquire


def _kg_entity_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    if "id" in d and d["id"] is not None:
        d["id"] = str(d["id"])
    for ts in ("created_at", "updated_at"):
        if ts in d and d[ts] is not None:
            d[ts] = d[ts].isoformat()
    return d


def _kg_rel_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    for f in ("id", "subject_id", "object_id", "source_session_id"):
        if f in d and d[f] is not None:
            d[f] = str(d[f])
    if "created_at" in d and d["created_at"] is not None:
        d["created_at"] = d["created_at"].isoformat()
    return d


async def db_find_or_create_entity(name: str, entity_type: str, aliases: list[str]) -> str:
    """
    Find an existing kg_entity by normalized name or alias, or create a new one.
    Returns the entity UUID as a string.
    """
    normalized = name.lower().strip()
    async with _acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM playbook.kg_entities WHERE LOWER(name) = $1 OR $1 = ANY(aliases)",
            normalized,
        )
        if row:
            entity_id = str(row["id"])
            # Merge any new aliases
            if aliases:
                await conn.execute(
                    "UPDATE playbook.kg_entities SET aliases = (SELECT array_agg(DISTINCT a) FROM unnest(aliases || $1::text[]) AS a), updated_at = NOW() WHERE id = $2::uuid",
                    aliases, entity_id,
                )
            return entity_id
        row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_entities (name, entity_type, aliases)
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
            SELECT id, predicate FROM playbook.kg_relationships
            WHERE subject_id = $1::uuid AND object_id = $2::uuid
              AND predicate_family = $3 AND is_active = TRUE
            """,
            subject_id, object_id, predicate_family,
        )

        if existing is None:
            await conn.execute(
                """
                INSERT INTO playbook.kg_relationships
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
            "UPDATE playbook.kg_relationships SET is_active = FALSE WHERE id = $1::uuid",
            old_id,
        )
        new_row = await conn.fetchrow(
            """
            INSERT INTO playbook.kg_relationships
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


async def db_list_kg_entities(
    search: str | None = None,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    conditions = []
    args: list[Any] = []
    idx = 0
    if search:
        idx += 1
        conditions.append(f"LOWER(e.name) LIKE $%d" % idx)
        args.append(f"%{search.lower()}%")
    if entity_type:
        idx += 1
        conditions.append(f"e.entity_type = $%d" % idx)
        args.append(entity_type)
    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    async with _acquire() as conn:
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*)::int AS total FROM playbook.kg_entities e{where}", *args
        )
        total = count_row["total"] if count_row else 0
        rows = await conn.fetch(
            f"""
            SELECT e.*,
                   (SELECT COUNT(*) FROM playbook.kg_relationships r
                    WHERE r.subject_id = e.id OR r.object_id = e.id)::int AS relationship_count
            FROM playbook.kg_entities e{where}
            ORDER BY e.updated_at DESC
            LIMIT {limit} OFFSET {offset}
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
    entity_id: str, direction: str = "both"
) -> list[dict[str, Any]]:
    conditions = []
    if direction == "outgoing":
        conditions.append("r.subject_id = $1::uuid")
    elif direction == "incoming":
        conditions.append("r.object_id = $1::uuid")
    else:
        conditions.append("(r.subject_id = $1::uuid OR r.object_id = $1::uuid)")
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT r.*,
                   s.name AS subject_name, s.entity_type AS subject_type,
                   o.name AS object_name, o.entity_type AS object_type
            FROM playbook.kg_relationships r
            JOIN playbook.kg_entities s ON s.id = r.subject_id
            JOIN playbook.kg_entities o ON o.id = r.object_id
            WHERE {conditions[0]} AND r.is_active = TRUE
            ORDER BY r.created_at DESC
            """,
            entity_id,
        )
    return [_kg_rel_to_dict(r) for r in rows]


async def db_search_kg(query: str) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.*,
                   (SELECT COUNT(*) FROM playbook.kg_relationships r
                    WHERE r.subject_id = e.id OR r.object_id = e.id)::int AS relationship_count
            FROM playbook.kg_entities e
            WHERE LOWER(e.name) LIKE $1 OR $2 = ANY(SELECT LOWER(a) FROM unnest(e.aliases) a)
            ORDER BY e.updated_at DESC LIMIT 50
            """,
            f"%{query.lower()}%", query.lower(),
        )
    return [_kg_entity_to_dict(r) for r in rows]


async def db_get_kg_stats() -> dict[str, Any]:
    async with _acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*)::int FROM playbook.kg_entities) AS total_entities,
                (SELECT COUNT(*)::int FROM playbook.kg_relationships WHERE is_active = TRUE) AS total_relationships,
                (SELECT COUNT(*)::int FROM playbook.kg_relationship_conflicts) AS total_conflicts,
                (SELECT COUNT(DISTINCT entity_type)::int FROM playbook.kg_entities) AS entity_types
            """
        )
    return dict(row) if row else {"total_entities": 0, "total_relationships": 0, "total_conflicts": 0, "entity_types": 0}


async def db_list_kg_conflicts(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.*, c.subject_name, c.object_name
            FROM playbook.kg_relationship_conflicts c
            ORDER BY c.detected_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit, offset,
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


# ── KG Graph / Deal-Partners ──────────────────────────────────────────────────

async def db_get_kg_graph(
    entity_types: list[str] | None = None,
    predicate_families: list[str] | None = None,
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
    where = " AND ".join(conditions)
    async with _acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT r.id, r.subject_id, r.object_id, r.predicate, r.predicate_family, r.confidence,
                   s.name AS subject_name, s.entity_type AS subject_type, s.aliases AS subject_aliases,
                   o.name AS object_name, o.entity_type AS object_type, o.aliases AS object_aliases
            FROM playbook.kg_relationships r
            JOIN playbook.kg_entities s ON s.id = r.subject_id
            JOIN playbook.kg_entities o ON o.id = r.object_id
            WHERE {where}
            ORDER BY r.created_at DESC
            LIMIT {limit}
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
            node_map[sid] = {"id": sid, "name": r["subject_name"], "entity_type": r["subject_type"],
                             "aliases": list(r["subject_aliases"] or [])}
        if oid not in node_map:
            node_map[oid] = {"id": oid, "name": r["object_name"], "entity_type": r["object_type"],
                             "aliases": list(r["object_aliases"] or [])}
        edges.append({
            "id": str(r["id"]),
            "source": sid,
            "target": oid,
            "predicate": r["predicate"],
            "predicate_family": r["predicate_family"],
            "confidence": float(r["confidence"]),
        })
    return {"nodes": list(node_map.values()), "edges": edges}


async def db_get_deal_partners() -> list[dict[str, Any]]:
    """Find pairs of persons connected to the same entity via transaction relationships."""
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
            )
            SELECT a.person_id AS person1_id, a.person_name AS person1_name,
                   b.person_id AS person2_id, b.person_name AS person2_name,
                   a.deal_entity_id, a.deal_entity_name,
                   a.predicate AS person1_predicate, b.predicate AS person2_predicate
            FROM person_deals a
            JOIN person_deals b ON a.deal_entity_id = b.deal_entity_id AND a.person_id < b.person_id
            ORDER BY a.person1_name, b.person2_name
            """
        )
    # Group by person pair
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
