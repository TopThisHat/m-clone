"""
LLM-based attribute clustering for batched research.

Groups campaign attributes into logical clusters, each with a research
question template. Clusters are cached per campaign so re-runs reuse
the same grouping. Handles incremental re-clustering when new attributes
are added.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.openai_factory import get_openai_client

logger = logging.getLogger(__name__)

MAX_CLUSTER_SIZE = 10  # Cap per devil's advocate recommendation


async def cluster_attributes(attributes: list[dict]) -> list[dict]:
    """
    Group attributes into logical research clusters using LLM.

    Input: [{"id": str, "label": str, "description": str|None}, ...]
    Output: [
        {
            "cluster_name": "ESG & Sustainability",
            "attribute_labels": ["has ESG policy", "publishes sustainability report"],
            "research_question": "What ESG policies... does {entity} have?"
        },
        ...
    ]

    Caps cluster size at MAX_CLUSTER_SIZE. If LLM produces larger clusters,
    they are split.
    """
    # Build prompt (truncate at 100 attributes to stay within token limits)
    attrs = attributes[:100]
    attr_text = "\n".join(
        f"- {a['label']}: {a.get('description') or 'N/A'}"
        for a in attrs
    )

    prompt = f"""Group these attributes into logical research clusters. Each cluster should contain
attributes that can be answered by a single, focused research query.

Attributes:
{attr_text}

Rules:
- Create 5-15 clusters (fewer is better if attributes are related)
- Each attribute must appear in exactly one cluster
- Maximum {MAX_CLUSTER_SIZE} attributes per cluster — split larger groups
- Generate a research question template for each cluster (use {{entity}} as placeholder)
- The question should be specific enough to find evidence for ALL attributes in the cluster
- Keep clusters thematically coherent (don't mix financial metrics with ESG policies)

Return JSON:
{{
    "clusters": [
        {{
            "cluster_name": "string",
            "attribute_labels": ["label1", "label2"],
            "research_question": "Does {{entity}} have ... ?"
        }}
    ]
}}"""

    resp = await get_openai_client().chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=3000,
    )
    raw = json.loads(resp.choices[0].message.content)
    clusters = raw.get("clusters", [])

    # Post-process: enforce max cluster size by splitting
    result = []
    for cluster in clusters:
        labels = cluster.get("attribute_labels", [])
        if len(labels) <= MAX_CLUSTER_SIZE:
            result.append(cluster)
        else:
            # Split into chunks of MAX_CLUSTER_SIZE
            for i in range(0, len(labels), MAX_CLUSTER_SIZE):
                chunk = labels[i:i + MAX_CLUSTER_SIZE]
                result.append({
                    "cluster_name": f"{cluster['cluster_name']} (part {i // MAX_CLUSTER_SIZE + 1})",
                    "attribute_labels": chunk,
                    "research_question": cluster.get("research_question", ""),
                })

    # Validate: every attribute label must appear exactly once
    attr_label_set = {a["label"] for a in attrs}
    clustered_labels = set()
    for c in result:
        for label in c.get("attribute_labels", []):
            clustered_labels.add(label)

    # Any unclustered attributes get their own "Uncategorized" cluster
    unclustered = attr_label_set - clustered_labels
    if unclustered:
        unclustered_list = sorted(unclustered)
        for i in range(0, len(unclustered_list), MAX_CLUSTER_SIZE):
            chunk = unclustered_list[i:i + MAX_CLUSTER_SIZE]
            result.append({
                "cluster_name": f"General Research (part {i // MAX_CLUSTER_SIZE + 1})" if len(unclustered_list) > MAX_CLUSTER_SIZE else "General Research",
                "attribute_labels": chunk,
                "research_question": "Research {entity} for the following characteristics: " + ", ".join(chunk),
            })

    return result


async def get_or_create_clusters(
    campaign_id: str,
    attributes: list[dict],
) -> list[dict]:
    """
    Get cached clusters for a campaign, or create them via LLM.

    Handles incremental re-clustering: if new attributes have been added
    since the last clustering, only the new attributes are clustered and
    appended as new clusters (existing clusters are preserved).

    Returns: [{"id": str, "cluster_name": str, "attribute_ids": [str, ...],
               "research_question_template": str}, ...]
    """
    from app.db.clusters import db_get_clusters, db_save_clusters

    existing_clusters = await db_get_clusters(campaign_id)

    # Build label→id map
    label_to_id = {a["label"]: str(a["id"]) for a in attributes}
    id_to_label = {str(a["id"]): a["label"] for a in attributes}

    if existing_clusters:
        # Check if all current attributes are covered
        clustered_ids = set()
        for c in existing_clusters:
            for aid in c.get("attribute_ids", []):
                clustered_ids.add(aid)

        current_ids = set(label_to_id.values())
        new_ids = current_ids - clustered_ids

        if not new_ids:
            # All attributes covered — return existing clusters
            # Filter out any deleted attributes
            valid_clusters = []
            for c in existing_clusters:
                valid_ids = [aid for aid in c["attribute_ids"] if aid in current_ids]
                if valid_ids:
                    valid_clusters.append({**c, "attribute_ids": valid_ids})
            return valid_clusters

        # Incremental: cluster only the new attributes
        new_attrs = [a for a in attributes if str(a["id"]) in new_ids]
        if new_attrs:
            new_clusters_raw = await cluster_attributes(new_attrs)

            # Convert labels to IDs and save
            new_cluster_records = []
            for c in new_clusters_raw:
                attr_ids = [
                    label_to_id[label]
                    for label in c.get("attribute_labels", [])
                    if label in label_to_id
                ]
                if attr_ids:
                    new_cluster_records.append({
                        "cluster_name": c["cluster_name"],
                        "attribute_ids": attr_ids,
                        "research_question_template": c.get("research_question", ""),
                    })

            if new_cluster_records:
                saved = await db_save_clusters(campaign_id, new_cluster_records)
                existing_clusters.extend(saved)

        return existing_clusters

    # No existing clusters — create from scratch
    clusters_raw = await cluster_attributes(attributes)

    cluster_records = []
    for c in clusters_raw:
        attr_ids = [
            label_to_id[label]
            for label in c.get("attribute_labels", [])
            if label in label_to_id
        ]
        if attr_ids:
            cluster_records.append({
                "cluster_name": c["cluster_name"],
                "attribute_ids": attr_ids,
                "research_question_template": c.get("research_question", ""),
            })

    return await db_save_clusters(campaign_id, cluster_records)
