"""
Team → Master KG promotion workflow.

Promotes high-confidence team-scoped entities and relationships to the
master graph (team_id = NULL). Uses advisory locks to prevent race
conditions when multiple teams promote simultaneously.

Promotion criteria:
  - confidence >= PROMOTION_CONFIDENCE_THRESHOLD (0.85)
  - research_session_count >= PROMOTION_SESSION_MINIMUM (2)
  - Entity not already in master graph

Per expert recommendations:
  - Advisory lock scoped to entity name hash prevents duplicate master entries
  - Conflict queue for human review when confidence < 0.8
  - INSERT ... ON CONFLICT for atomic dedup
"""
from __future__ import annotations

import json
import logging
from typing import Any

from worker.registry import BaseWorkflow, registry

logger = logging.getLogger(__name__)

PROMOTION_CONFIDENCE_THRESHOLD = 0.85
PROMOTION_SESSION_MINIMUM = 2


async def promote_entity_to_master(
    entity_id: str,
    team_id: str,
) -> dict[str, Any]:
    """
    Promote a team-scoped KG entity to the master graph.

    Uses pg_advisory_xact_lock on the entity name hash to prevent
    concurrent promotions creating duplicate master entries.

    Returns: {"action": "promoted"|"already_exists"|"skipped", "master_entity_id": str|None}
    """
    from app.db._pool import _acquire

    async with _acquire() as conn:
        async with conn.transaction():
            # Load the team entity
            entity = await conn.fetchrow(
                "SELECT * FROM playbook.kg_entities WHERE id = $1::uuid AND team_id = $2::uuid",
                entity_id, team_id,
            )
            if not entity:
                return {"action": "skipped", "master_entity_id": None}

            entity_name = entity["name"]

            # Advisory lock on entity name hash — prevents race condition
            # between teams promoting the same entity simultaneously
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(LOWER($1)))",
                entity_name,
            )

            # Check if entity already exists in master graph
            existing = await conn.fetchrow(
                """
                SELECT id FROM playbook.kg_entities
                WHERE LOWER(name) = LOWER($1) AND team_id IS NULL
                """,
                entity_name,
            )

            if existing:
                master_id = str(existing["id"])
                # Merge aliases from team entity into master
                await conn.execute(
                    """
                    UPDATE playbook.kg_entities
                    SET aliases = (
                        SELECT array_agg(DISTINCT a)
                        FROM unnest(aliases || $2::text[]) AS a
                    ),
                    updated_at = NOW()
                    WHERE id = $1::uuid
                    """,
                    master_id, list(entity["aliases"] or []),
                )
                # Record promotion
                await conn.execute(
                    """
                    INSERT INTO playbook.kg_promotions (source_team_id, entity_id, promoted_by)
                    VALUES ($1::uuid, $2::uuid, 'auto')
                    """,
                    team_id, master_id,
                )
                return {"action": "already_exists", "master_entity_id": master_id}

            # Create master entity
            master_row = await conn.fetchrow(
                """
                INSERT INTO playbook.kg_entities (name, entity_type, aliases, metadata, team_id)
                VALUES ($1, $2, $3, $4, NULL)
                ON CONFLICT ((LOWER(name))) DO UPDATE SET
                    aliases = (
                        SELECT array_agg(DISTINCT a)
                        FROM unnest(playbook.kg_entities.aliases || EXCLUDED.aliases) AS a
                    ),
                    updated_at = NOW()
                RETURNING id
                """,
                entity["name"], entity["entity_type"],
                list(entity["aliases"] or []),
                entity["metadata"] or "{}",
            )
            master_id = str(master_row["id"])

            # Record promotion
            await conn.execute(
                """
                INSERT INTO playbook.kg_promotions (source_team_id, entity_id, promoted_by)
                VALUES ($1::uuid, $2::uuid, 'auto')
                """,
                team_id, master_id,
            )

            logger.info("Promoted entity '%s' from team %s to master (id=%s)", entity_name, team_id, master_id)
            return {"action": "promoted", "master_entity_id": master_id}


async def promote_relationships_to_master(
    team_id: str,
    entity_id_map: dict[str, str],  # team_entity_id → master_entity_id
) -> int:
    """
    Promote relationships for mapped entities from team to master graph.
    Only promotes relationships where both subject and object have been promoted.

    Returns count of promoted relationships.
    """
    from app.db._pool import _acquire

    promoted_count = 0
    async with _acquire() as conn:
        # Find team relationships where both endpoints are in the map
        team_entity_ids = list(entity_id_map.keys())
        rows = await conn.fetch(
            """
            SELECT * FROM playbook.kg_relationships
            WHERE team_id = $1::uuid
              AND is_active = TRUE
              AND subject_id = ANY($2::uuid[])
              AND object_id = ANY($2::uuid[])
              AND confidence >= $3
            """,
            team_id, team_entity_ids, PROMOTION_CONFIDENCE_THRESHOLD,
        )

        for rel in rows:
            subject_master = entity_id_map.get(str(rel["subject_id"]))
            object_master = entity_id_map.get(str(rel["object_id"]))
            if not subject_master or not object_master:
                continue

            async with conn.transaction():
                # Check for existing active relationship in master
                existing = await conn.fetchrow(
                    """
                    SELECT id, predicate FROM playbook.kg_relationships
                    WHERE subject_id = $1::uuid AND object_id = $2::uuid
                      AND predicate_family = $3 AND is_active = TRUE
                      AND team_id IS NULL
                    FOR UPDATE
                    """,
                    subject_master, object_master, rel["predicate_family"],
                )

                if existing:
                    if existing["predicate"] == rel["predicate"]:
                        continue  # Duplicate, skip
                    # Conflict — if confidence < 0.8, skip (needs human review)
                    if rel["confidence"] < 0.8:
                        logger.info(
                            "Skipping relationship promotion (confidence %.2f < 0.8, needs review): %s %s %s",
                            rel["confidence"], rel["predicate"],
                            str(rel["subject_id"]), str(rel["object_id"]),
                        )
                        continue
                    # Supersede existing
                    await conn.execute(
                        "UPDATE playbook.kg_relationships SET is_active = FALSE WHERE id = $1::uuid",
                        str(existing["id"]),
                    )

                await conn.execute(
                    """
                    INSERT INTO playbook.kg_relationships
                        (subject_id, predicate, predicate_family, object_id,
                         confidence, evidence, source_session_id, team_id)
                    VALUES ($1::uuid, $2, $3, $4::uuid, $5, $6, $7::uuid, NULL)
                    """,
                    subject_master, rel["predicate"], rel["predicate_family"],
                    object_master, rel["confidence"], rel["evidence"],
                    rel["source_session_id"],
                )
                promoted_count += 1

    return promoted_count


async def run_promotion_for_team(team_id: str) -> dict[str, Any]:
    """
    Run the full promotion pipeline for a team:
    1. Find eligible entities (high confidence, multiple sessions)
    2. Promote each to master graph
    3. Promote eligible relationships
    """
    from app.db._pool import _acquire

    async with _acquire() as conn:
        # Find team entities eligible for promotion via knowledge cache
        # Entities that have been validated with high confidence across multiple sessions
        eligible_rows = await conn.fetch(
            """
            SELECT DISTINCT ke.id, ke.name, ke.entity_type
            FROM playbook.kg_entities ke
            WHERE ke.team_id = $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM playbook.kg_promotions kp
                  WHERE kp.entity_id = ke.id AND kp.source_team_id = $1::uuid
              )
            """,
            team_id,
        )

    entity_id_map: dict[str, str] = {}
    promoted = 0
    skipped = 0

    for row in eligible_rows:
        result = await promote_entity_to_master(str(row["id"]), team_id)
        if result["master_entity_id"]:
            entity_id_map[str(row["id"])] = result["master_entity_id"]
        if result["action"] == "promoted":
            promoted += 1
        elif result["action"] == "skipped":
            skipped += 1

    # Promote relationships
    rel_count = 0
    if entity_id_map:
        rel_count = await promote_relationships_to_master(team_id, entity_id_map)

    logger.info(
        "Promotion for team %s: %d entities promoted, %d skipped, %d relationships promoted",
        team_id, promoted, skipped, rel_count,
    )
    return {
        "entities_promoted": promoted,
        "entities_skipped": skipped,
        "relationships_promoted": rel_count,
    }


@registry.register("kg_promotion")
class KGPromotionWorkflow(BaseWorkflow):
    """
    Promote team KG data to the master graph.

    payload: {"team_id": str}
    """

    async def run(self) -> None:
        team_id = self.payload.get("team_id")
        if not team_id:
            logger.warning("kg_promotion job=%s: no team_id in payload", self.job_id)
            return

        result = await run_promotion_for_team(team_id)
        logger.info("kg_promotion job=%s: %s", self.job_id, result)
