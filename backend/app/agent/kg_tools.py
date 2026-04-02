"""KG Chat tools — six structured functions for querying the knowledge graph.

Security invariant: all SQL uses parameterized queries. No f-strings in SQL.
All functions validate inputs before hitting the database.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import asyncpg

from app.db._pool import _acquire

logger = logging.getLogger(__name__)

# ── Pre-defined aggregate queries (no dynamic SQL) ────────────────────────────

_AGGREGATE_QUERIES: dict[str, str] = {
    "entity_type_counts": """
        SELECT entity_type, COUNT(*) AS count
        FROM playbook.kg_entities
        WHERE team_id = $1::uuid
        GROUP BY entity_type
        ORDER BY count DESC
    """,
    "relationship_family_counts": """
        SELECT predicate_family, COUNT(*) AS count
        FROM playbook.kg_relationships
        WHERE team_id = $1::uuid AND is_active = TRUE
        GROUP BY predicate_family
        ORDER BY count DESC
    """,
    "most_connected": """
        SELECT e.id, e.name, e.entity_type,
               COUNT(r.id) AS relationship_count
        FROM playbook.kg_entities e
        LEFT JOIN playbook.kg_relationships r
            ON (r.subject_id = e.id OR r.object_id = e.id)
            AND r.is_active = TRUE
            AND r.team_id = $1::uuid
        WHERE e.team_id = $1::uuid
        GROUP BY e.id, e.name, e.entity_type
        ORDER BY relationship_count DESC
        LIMIT 20
    """,
    "recent_entities": """
        SELECT id, name, entity_type, created_at
        FROM playbook.kg_entities
        WHERE team_id = $1::uuid
        ORDER BY created_at DESC
        LIMIT 20
    """,
    "predicate_counts": """
        SELECT predicate, COUNT(*) AS count
        FROM playbook.kg_relationships
        WHERE team_id = $1::uuid AND is_active = TRUE
        GROUP BY predicate
        ORDER BY count DESC
    """,
}


def _validate_uuid(value: str, name: str) -> str:
    """Raise ValueError if value is not a valid UUID string."""
    try:
        UUID(str(value))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid UUID for parameter '{name}': {value!r}")
    return str(value)


def _validate_positive_int(value: int, name: str, max_val: int = 100) -> int:
    if not isinstance(value, int) or value < 1 or value > max_val:
        raise ValueError(f"Parameter '{name}' must be an integer between 1 and {max_val}")
    return value


# ── Tool 1: search_kg_entities ────────────────────────────────────────────────

async def search_kg_entities(
    team_id: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search for KG entities by name using pg_trgm similarity.

    Returns up to `limit` entities sorted by trigram similarity to `query`.
    All results are scoped to `team_id`.
    """
    _validate_uuid(team_id, "team_id")
    if not query or not query.strip():
        raise ValueError("query must not be empty")
    limit = _validate_positive_int(limit, "limit", max_val=50)

    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, name, entity_type, aliases, description,
                disambiguation_context, created_at, updated_at,
                similarity(LOWER(name), LOWER($2)) AS score
            FROM playbook.kg_entities
            WHERE team_id = $1::uuid
              AND similarity(LOWER(name), LOWER($2)) > 0.1
            ORDER BY score DESC
            LIMIT $3
            """,
            team_id,
            query.strip(),
            limit,
        )

    results = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["team_id"] = team_id
        if d.get("aliases") is None:
            d["aliases"] = []
        for ts in ("created_at", "updated_at"):
            if d.get(ts) is not None:
                d[ts] = d[ts].isoformat()
        results.append(d)
    return results


# ── Tool 2: get_entity_relationships ─────────────────────────────────────────

async def get_entity_relationships(
    team_id: str,
    entity_id: str,
    family: str | None = None,
    direction: str | None = None,
) -> dict[str, Any]:
    """Fetch relationships for an entity, optionally filtered by family/direction.

    Args:
        team_id: Team scope.
        entity_id: UUID of the entity.
        family: Optional predicate family filter (e.g. 'ownership', 'employment').
        direction: One of 'outgoing', 'incoming', or None for both.

    Returns dict with 'entity' and 'relationships' keys.
    """
    _validate_uuid(team_id, "team_id")
    _validate_uuid(entity_id, "entity_id")
    if direction and direction not in ("outgoing", "incoming"):
        raise ValueError("direction must be 'outgoing', 'incoming', or None")

    async with _acquire() as conn:
        entity_row = await conn.fetchrow(
            "SELECT id, name, entity_type, aliases, description FROM playbook.kg_entities "
            "WHERE id = $1::uuid AND team_id = $2::uuid",
            entity_id, team_id,
        )
        if entity_row is None:
            return {"entity": None, "relationships": [], "error": "Entity not found"}

        # Fixed parameterized query — no dynamic SQL.
        # $3 = family filter (NULL means no filter)
        # $4 = direction: 'outgoing' | 'incoming' | NULL (both)
        rows = await conn.fetch(
            """
            SELECT
                r.id, r.subject_id, r.object_id, r.predicate,
                r.predicate_family, r.confidence, r.evidence, r.created_at,
                se.name AS subject_name, se.entity_type AS subject_type,
                oe.name AS object_name,  oe.entity_type AS object_type
            FROM playbook.kg_relationships r
            JOIN playbook.kg_entities se ON se.id = r.subject_id
            JOIN playbook.kg_entities oe ON oe.id = r.object_id
            WHERE r.team_id = $1::uuid
              AND r.is_active = TRUE
              AND (
                  CASE
                    WHEN $4::text = 'outgoing' THEN r.subject_id = $2::uuid
                    WHEN $4::text = 'incoming' THEN r.object_id  = $2::uuid
                    ELSE r.subject_id = $2::uuid OR r.object_id = $2::uuid
                  END
              )
              AND ($3::text IS NULL OR r.predicate_family = $3)
            ORDER BY r.confidence DESC, r.created_at DESC
            LIMIT 100
            """,
            team_id,
            entity_id,
            family,
            direction,
        )

    relationships = []
    for r in rows:
        d = dict(r)
        for uid in ("id", "subject_id", "object_id"):
            if d.get(uid) is not None:
                d[uid] = str(d[uid])
        if d.get("created_at") is not None:
            d["created_at"] = d["created_at"].isoformat()
        relationships.append(d)

    entity_dict = dict(entity_row)
    entity_dict["id"] = str(entity_dict["id"])
    if entity_dict.get("aliases") is None:
        entity_dict["aliases"] = []

    return {"entity": entity_dict, "relationships": relationships}


# ── Tool 3: find_connections ──────────────────────────────────────────────────

async def find_connections(
    team_id: str,
    source_id: str,
    target_id: str,
    max_hops: int = 3,
) -> dict[str, Any]:
    """Find shortest paths between two entities via recursive CTE BFS.

    Returns paths as lists of (entity, relationship) alternating nodes.
    Limited to `max_hops` edge traversals.
    """
    _validate_uuid(team_id, "team_id")
    _validate_uuid(source_id, "source_id")
    _validate_uuid(target_id, "target_id")
    max_hops = _validate_positive_int(max_hops, "max_hops", max_val=5)

    if source_id == target_id:
        return {"paths": [], "message": "Source and target are the same entity"}

    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            WITH RECURSIVE bfs AS (
                -- Seed: start from source
                SELECT
                    r.id            AS rel_id,
                    r.subject_id    AS from_id,
                    r.object_id     AS to_id,
                    r.predicate,
                    r.predicate_family,
                    ARRAY[r.subject_id] AS visited,
                    ARRAY[r.id]         AS path_rels,
                    1                   AS hops
                FROM playbook.kg_relationships r
                WHERE r.team_id = $1::uuid
                  AND r.is_active = TRUE
                  AND r.subject_id = $2::uuid

                UNION ALL

                -- Expand: follow edges not yet visited
                SELECT
                    r.id,
                    r.subject_id,
                    r.object_id,
                    r.predicate,
                    r.predicate_family,
                    bfs.visited || r.subject_id,
                    bfs.path_rels || r.id,
                    bfs.hops + 1
                FROM playbook.kg_relationships r
                JOIN bfs ON bfs.to_id = r.subject_id
                WHERE r.team_id = $1::uuid
                  AND r.is_active = TRUE
                  AND NOT (r.subject_id = ANY(bfs.visited))
                  AND bfs.hops < $4
            )
            SELECT path_rels, visited || to_id AS full_path, hops
            FROM bfs
            WHERE to_id = $3::uuid
            ORDER BY hops ASC
            LIMIT 5
            """,
            team_id,
            source_id,
            target_id,
            max_hops,
        )

    if not rows:
        return {
            "source_id": source_id,
            "target_id": target_id,
            "paths": [],
            "message": f"No path found within {max_hops} hops",
        }

    # Collect all entity and relationship IDs from paths
    all_entity_ids: set[str] = set()
    all_rel_ids: set[str] = set()
    for r in rows:
        all_entity_ids.update(str(uid) for uid in r["full_path"])
        all_rel_ids.update(str(rid) for rid in r["path_rels"])

    async with _acquire() as conn:
        entity_rows = await conn.fetch(
            "SELECT id, name, entity_type FROM playbook.kg_entities "
            "WHERE id = ANY($1::uuid[]) AND team_id = $2::uuid",
            [UUID(eid) for eid in all_entity_ids],
            team_id,
        )
        rel_rows = await conn.fetch(
            "SELECT id, subject_id, object_id, predicate, predicate_family, confidence "
            "FROM playbook.kg_relationships WHERE id = ANY($1::uuid[])",
            [UUID(rid) for rid in all_rel_ids],
        )

    entities = {str(r["id"]): {"id": str(r["id"]), "name": r["name"], "entity_type": r["entity_type"]} for r in entity_rows}
    rels = {
        str(r["id"]): {
            "id": str(r["id"]),
            "subject_id": str(r["subject_id"]),
            "object_id": str(r["object_id"]),
            "predicate": r["predicate"],
            "predicate_family": r["predicate_family"],
            "confidence": r["confidence"],
        }
        for r in rel_rows
    }

    paths = []
    for row in rows:
        path_entities = [entities.get(str(uid)) for uid in row["full_path"]]
        path_rels = [rels.get(str(rid)) for rid in row["path_rels"]]
        paths.append({
            "hops": row["hops"],
            "entities": [e for e in path_entities if e],
            "relationships": [r for r in path_rels if r],
        })

    return {
        "source_id": source_id,
        "target_id": target_id,
        "paths": paths,
    }


# ── Tool 4: aggregate_kg ──────────────────────────────────────────────────────

async def aggregate_kg(
    team_id: str,
    query_name: str,
) -> dict[str, Any]:
    """Run a pre-defined aggregate query against the KG.

    Only named queries in the allow-list are accepted — no dynamic SQL.
    Available query_names: entity_type_counts, relationship_family_counts,
    most_connected, recent_entities, predicate_counts.
    """
    _validate_uuid(team_id, "team_id")
    sql = _AGGREGATE_QUERIES.get(query_name)
    if sql is None:
        available = ", ".join(sorted(_AGGREGATE_QUERIES))
        raise ValueError(
            f"Unknown query_name '{query_name}'. Available: {available}"
        )

    async with _acquire() as conn:
        rows = await conn.fetch(sql, team_id)

    results = []
    for r in rows:
        d = dict(r)
        for key, val in d.items():
            if isinstance(val, UUID):
                d[key] = str(val)
        results.append(d)

    return {"query_name": query_name, "results": results}


# ── Tool 5: get_entity_details ────────────────────────────────────────────────

async def get_entity_details(
    team_id: str,
    entity_ids: list[str],
) -> list[dict[str, Any]]:
    """Batch-fetch full details for a list of entity UUIDs.

    Returns entities found within the team scope. Missing IDs are silently skipped.
    """
    _validate_uuid(team_id, "team_id")
    if not entity_ids:
        return []
    if len(entity_ids) > 100:
        raise ValueError("entity_ids list must not exceed 100 items")

    validated_ids = []
    for eid in entity_ids:
        _validate_uuid(str(eid), "entity_ids[]")
        validated_ids.append(UUID(str(eid)))

    async with _acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                e.id, e.name, e.entity_type, e.aliases, e.description,
                e.disambiguation_context, e.metadata, e.created_at, e.updated_at,
                COUNT(r.id) AS relationship_count
            FROM playbook.kg_entities e
            LEFT JOIN playbook.kg_relationships r
                ON (r.subject_id = e.id OR r.object_id = e.id)
                AND r.is_active = TRUE
            WHERE e.id = ANY($1::uuid[]) AND e.team_id = $2::uuid
            GROUP BY e.id
            ORDER BY e.name
            """,
            validated_ids,
            team_id,
        )

    results = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        if d.get("aliases") is None:
            d["aliases"] = []
        if d.get("metadata") is None:
            d["metadata"] = {}
        for ts in ("created_at", "updated_at"):
            if d.get(ts) is not None:
                d[ts] = d[ts].isoformat()
        results.append(d)
    return results


# ── Tool 6: explore_neighborhood ─────────────────────────────────────────────

async def explore_neighborhood(
    team_id: str,
    entity_id: str,
    depth: int = 1,
) -> dict[str, Any]:
    """Return an entity and its neighbor graph up to `depth` hops.

    Uses existing db_get_neighbors pattern extended to support depth > 1 via
    iterative expansion.
    """
    _validate_uuid(team_id, "team_id")
    _validate_uuid(entity_id, "entity_id")
    depth = _validate_positive_int(depth, "depth", max_val=3)

    async with _acquire() as conn:
        center_row = await conn.fetchrow(
            "SELECT id, name, entity_type, aliases, description "
            "FROM playbook.kg_entities WHERE id = $1::uuid AND team_id = $2::uuid",
            entity_id, team_id,
        )
        if center_row is None:
            return {"entity": None, "nodes": [], "edges": [], "error": "Entity not found"}

        # BFS up to `depth` hops
        visited_ids: set[str] = {entity_id}
        frontier: set[str] = {entity_id}
        all_edges: list[dict[str, Any]] = []

        for _ in range(depth):
            if not frontier:
                break
            frontier_uuids = [UUID(fid) for fid in frontier]
            rows = await conn.fetch(
                """
                SELECT
                    r.id, r.subject_id, r.object_id, r.predicate, r.predicate_family, r.confidence,
                    se.name AS subject_name, se.entity_type AS subject_type,
                    oe.name AS object_name,  oe.entity_type AS object_type
                FROM playbook.kg_relationships r
                JOIN playbook.kg_entities se ON se.id = r.subject_id
                JOIN playbook.kg_entities oe ON oe.id = r.object_id
                WHERE r.team_id = $1::uuid
                  AND r.is_active = TRUE
                  AND (r.subject_id = ANY($2::uuid[]) OR r.object_id = ANY($2::uuid[]))
                LIMIT 200
                """,
                team_id,
                frontier_uuids,
            )
            new_frontier: set[str] = set()
            for r in rows:
                sid = str(r["subject_id"])
                oid = str(r["object_id"])
                edge = {
                    "id": str(r["id"]),
                    "subject_id": sid,
                    "object_id": oid,
                    "predicate": r["predicate"],
                    "predicate_family": r["predicate_family"],
                    "confidence": r["confidence"],
                    "subject_name": r["subject_name"],
                    "subject_type": r["subject_type"],
                    "object_name": r["object_name"],
                    "object_type": r["object_type"],
                }
                # Deduplicate edges by id
                if not any(e["id"] == edge["id"] for e in all_edges):
                    all_edges.append(edge)
                if sid not in visited_ids:
                    new_frontier.add(sid)
                    visited_ids.add(sid)
                if oid not in visited_ids:
                    new_frontier.add(oid)
                    visited_ids.add(oid)
            frontier = new_frontier

        # Fetch all node details
        all_node_uuids = [UUID(nid) for nid in visited_ids]
        node_rows = await conn.fetch(
            "SELECT id, name, entity_type, aliases, description "
            "FROM playbook.kg_entities WHERE id = ANY($1::uuid[]) AND team_id = $2::uuid",
            all_node_uuids, team_id,
        )

    nodes = []
    for r in node_rows:
        d = dict(r)
        d["id"] = str(d["id"])
        if d.get("aliases") is None:
            d["aliases"] = []
        nodes.append(d)

    center_dict = dict(center_row)
    center_dict["id"] = str(center_dict["id"])
    if center_dict.get("aliases") is None:
        center_dict["aliases"] = []

    return {
        "entity": center_dict,
        "depth": depth,
        "nodes": nodes,
        "edges": all_edges,
        "node_count": len(nodes),
        "edge_count": len(all_edges),
    }


# ── OpenAI tool schema definitions ───────────────────────────────────────────

KG_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_kg_entities",
            "description": "Search the knowledge graph for entities by name using fuzzy trigram matching. Returns entities sorted by similarity score.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query to match against entity names"},
                    "limit": {"type": "integer", "description": "Maximum number of results to return (1-50, default 10)", "default": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_relationships",
            "description": "Get all relationships for a specific entity, optionally filtered by predicate family or direction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "UUID of the entity"},
                    "family": {"type": "string", "description": "Optional predicate family to filter by (e.g. 'ownership', 'employment')"},
                    "direction": {"type": "string", "enum": ["outgoing", "incoming"], "description": "Optional direction filter"},
                },
                "required": ["entity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_connections",
            "description": "Find the shortest path(s) between two entities in the knowledge graph using BFS traversal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "UUID of the source entity"},
                    "target_id": {"type": "string", "description": "UUID of the target entity"},
                    "max_hops": {"type": "integer", "description": "Maximum number of hops to traverse (1-5, default 3)", "default": 3},
                },
                "required": ["source_id", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_kg",
            "description": "Run a pre-defined aggregate analysis query on the knowledge graph. Available: entity_type_counts, relationship_family_counts, most_connected, recent_entities, predicate_counts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query_name": {
                        "type": "string",
                        "enum": list(_AGGREGATE_QUERIES.keys()),
                        "description": "Name of the pre-defined aggregate query to run",
                    },
                },
                "required": ["query_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entity_details",
            "description": "Batch-fetch full details for one or more entities by their UUIDs, including relationship count.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of entity UUIDs to fetch (max 100)",
                    },
                },
                "required": ["entity_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explore_neighborhood",
            "description": "Explore the neighborhood of an entity — returns the entity, its neighbors, and all connecting edges up to the specified depth.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string", "description": "UUID of the central entity"},
                    "depth": {"type": "integer", "description": "Number of hops to explore from the entity (1-3, default 1)", "default": 1},
                },
                "required": ["entity_id"],
            },
        },
    },
]


async def execute_kg_tool(
    name: str,
    args: dict[str, Any],
    team_id: str,
) -> str:
    """Dispatch a KG tool call by name and return JSON-serialized results."""
    try:
        if name == "search_kg_entities":
            result = await search_kg_entities(
                team_id=team_id,
                query=args["query"],
                limit=args.get("limit", 10),
            )
        elif name == "get_entity_relationships":
            result = await get_entity_relationships(
                team_id=team_id,
                entity_id=args["entity_id"],
                family=args.get("family"),
                direction=args.get("direction"),
            )
        elif name == "find_connections":
            result = await find_connections(
                team_id=team_id,
                source_id=args["source_id"],
                target_id=args["target_id"],
                max_hops=args.get("max_hops", 3),
            )
        elif name == "aggregate_kg":
            result = await aggregate_kg(
                team_id=team_id,
                query_name=args["query_name"],
            )
        elif name == "get_entity_details":
            result = await get_entity_details(
                team_id=team_id,
                entity_ids=args["entity_ids"],
            )
        elif name == "explore_neighborhood":
            result = await explore_neighborhood(
                team_id=team_id,
                entity_id=args["entity_id"],
                depth=args.get("depth", 1),
            )
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

        return json.dumps(result, default=str)
    except ValueError as exc:
        logger.warning("KG tool %s validation error: %s", name, exc)
        return json.dumps({"error": str(exc)})
    except Exception as exc:
        logger.exception("KG tool %s execution error", name)
        return json.dumps({"error": f"Tool execution failed: {exc}"})
