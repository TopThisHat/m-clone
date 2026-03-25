from ._pool import DatabaseNotConfigured, get_pool, close_pool
from ._schema import init_schema

# ── Sessions ──────────────────────────────────────────────────────────────────
from .sessions import (
    db_list_sessions,
    db_get_session,
    db_get_public_session,
    db_create_session,
    db_update_session,
    db_delete_session,
    db_fork_session,
    db_subscribe,
    db_unsubscribe,
    db_is_subscribed,
    db_get_subscriber_sids,
    db_heartbeat_presence,
    db_get_active_viewers,
    db_get_session_diff,
)

# ── Users ─────────────────────────────────────────────────────────────────────
from .users import (
    db_upsert_user,
    db_get_user,
    db_update_user_theme,
    db_is_super_admin,
)

# ── Teams ─────────────────────────────────────────────────────────────────────
from .teams import (
    db_create_team,
    db_get_team,
    db_get_team_by_id,
    db_list_user_teams,
    db_update_team,
    db_delete_team,
    db_list_team_members,
    db_get_member_role,
    db_add_member,
    db_update_member_role,
    db_remove_member,
    db_share_session_to_team,
    db_unshare_session,
    db_get_team_sessions,
    db_get_session_teams,
    db_get_session_mentionable_users,
    db_pin_session,
    db_unpin_session,
    db_get_pinned_sessions,
    db_list_team_member_sids,
    db_is_team_member,
    db_record_activity,
    db_list_team_activity,
)

# ── Comments ──────────────────────────────────────────────────────────────────
from .comments import (
    db_create_comment,
    db_list_comments,
    db_get_comment,
    db_delete_comment,
    db_update_comment,
    db_resolve_suggestion,
    db_toggle_reaction,
    db_get_reactions_bulk,
)

# ── Notifications ─────────────────────────────────────────────────────────────
from .notifications import (
    db_create_notification,
    db_list_notifications,
    db_mark_notification_read,
    db_mark_all_notifications_read,
)

# ── Monitors ──────────────────────────────────────────────────────────────────
from .monitors import (
    db_create_monitor,
    db_list_monitors,
    db_delete_monitor,
    db_get_monitor,
    db_update_monitor,
    db_list_monitor_runs,
    db_get_due_monitors,
    db_update_monitor_run,
)

# ── Campaigns ─────────────────────────────────────────────────────────────────
from .campaigns import (
    db_create_campaign,
    db_list_campaigns,
    db_get_campaign,
    db_update_campaign,
    db_delete_campaign,
    db_clone_campaign,
    db_cancel_job,
    db_get_due_campaigns,
    db_update_campaign_next_run,
    db_get_campaign_stats,
    db_import_entities,
    db_import_attributes,
    db_export_campaign_results,
    db_transition_campaign_status,
    db_get_campaign_status_audit,
)

# ── Entities ──────────────────────────────────────────────────────────────────
from .entities import (
    DuplicateLabelError,
    db_create_entity,
    db_bulk_create_entities,
    db_list_entities,
    db_get_entity,
    db_delete_entity,
    db_update_entity,
    db_get_entity_metadata,
    db_set_entity_metadata,
    db_delete_entity_metadata,
    db_set_external_id,
    db_get_external_ids,
    db_delete_external_id,
)

# ── Attributes ────────────────────────────────────────────────────────────────
from .attributes import (
    db_create_attribute,
    db_bulk_create_attributes,
    db_list_attributes,
    db_get_attribute,
    db_update_attribute,
    db_delete_attribute,
)

# ── Validation ────────────────────────────────────────────────────────────────
from .validation import (
    db_create_validation_job,
    db_create_and_enqueue_validation_job,
    db_list_validation_jobs,
    db_get_validation_job,
    db_update_validation_job,
    db_get_job_details,
    db_increment_job_progress,
    db_insert_result,
    db_list_results,
    db_get_scores,
    db_recompute_scores,
    db_get_live_scores,
    db_get_entity_cross_campaign,
    db_get_job_combined_report,
    db_get_score_trends,
    db_compare_jobs,
    db_insert_results_batch,
)

# ── Knowledge ─────────────────────────────────────────────────────────────────
from .knowledge import (
    db_lookup_knowledge,
    db_get_knowledge_for_campaign,
    db_lookup_knowledge_batch,
    db_check_staleness_batch,
)

# ── Knowledge Graph ───────────────────────────────────────────────────────────
from .knowledge_graph import (
    db_find_or_create_entity,
    db_find_similar_entities,
    db_merge_kg_entities,
    db_upsert_relationship,
    db_list_kg_entities,
    db_get_kg_entity,
    db_get_kg_relationship,
    db_get_entity_relationships,
    db_search_kg,
    db_get_kg_stats,
    db_list_kg_conflicts,
    db_get_kg_graph,
    db_get_deal_partners,
    db_update_kg_entity,
    db_delete_kg_entity,
    db_update_kg_relationship,
    db_delete_kg_relationship,
    db_query_kg,
    db_get_neighbors,
)

# ── Templates ─────────────────────────────────────────────────────────────────
from .templates import (
    db_list_attribute_templates,
    db_create_attribute_template,
    db_delete_attribute_template,
)

# ── Library ───────────────────────────────────────────────────────────────────
from .library import (
    db_list_entity_library,
    db_create_entity_library,
    db_bulk_create_entity_library,
    db_update_entity_library,
    db_delete_entity_library,
    db_list_attribute_library,
    db_create_attribute_library,
    db_bulk_create_attribute_library,
    db_update_attribute_library,
    db_delete_attribute_library,
    db_import_entities_from_library,
    db_import_attributes_from_library,
)

# ── Programs ─────────────────────────────────────────────────────────────────
from .programs import (
    db_create_program,
    db_list_programs,
    db_get_program,
    db_update_program,
    db_delete_program,
)

# ── Scores ───────────────────────────────────────────────────────────────────
from .scores import (
    db_recalculate_scores,
    db_mark_scores_stale,
    db_mark_scores_fresh,
    db_get_score,
    db_list_campaign_scores,
)

# ── Clusters ─────────────────────────────────────────────────────────────────
from .clusters import (
    db_get_clusters,
    db_save_clusters,
    db_delete_clusters,
)

# ── Research Jobs / Job Queue ─────────────────────────────────────────────────
from .jobs import (
    db_create_job,
    db_update_job,
    db_get_job,
    db_list_dead_jobs,
    db_get_queue_job_owner,
    db_retry_dead_job,
)
