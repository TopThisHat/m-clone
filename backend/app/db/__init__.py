from ._pool import DatabaseNotConfigured as DatabaseNotConfigured, get_pool as get_pool, close_pool as close_pool, _acquire_team as _acquire_team
from ._schema import init_schema as init_schema
from ._schema import verify_client_lookup_prerequisites as verify_client_lookup_prerequisites

# ── Sessions ──────────────────────────────────────────────────────────────────
from .sessions import (
    db_list_sessions as db_list_sessions,
    db_get_session as db_get_session,
    db_get_session_doc_key as db_get_session_doc_key,
    db_get_public_session as db_get_public_session,
    db_create_session as db_create_session,
    db_update_session as db_update_session,
    db_delete_session as db_delete_session,
    db_fork_session as db_fork_session,
    db_subscribe as db_subscribe,
    db_unsubscribe as db_unsubscribe,
    db_is_subscribed as db_is_subscribed,
    db_get_subscriber_sids as db_get_subscriber_sids,
    db_heartbeat_presence as db_heartbeat_presence,
    db_get_active_viewers as db_get_active_viewers,
    db_get_session_diff as db_get_session_diff,
)

# ── Users ─────────────────────────────────────────────────────────────────────
from .users import (
    db_upsert_user as db_upsert_user,
    db_get_user as db_get_user,
    db_update_user_theme as db_update_user_theme,
    db_is_super_admin as db_is_super_admin,
)

# ── Teams ─────────────────────────────────────────────────────────────────────
from .teams import (
    db_create_team as db_create_team,
    db_get_team as db_get_team,
    db_get_team_by_id as db_get_team_by_id,
    db_list_user_teams as db_list_user_teams,
    db_update_team as db_update_team,
    db_delete_team as db_delete_team,
    db_list_team_members as db_list_team_members,
    db_get_member_role as db_get_member_role,
    db_add_member as db_add_member,
    db_update_member_role as db_update_member_role,
    db_remove_member as db_remove_member,
    db_share_session_to_team as db_share_session_to_team,
    db_unshare_session as db_unshare_session,
    db_get_team_sessions as db_get_team_sessions,
    db_get_session_teams as db_get_session_teams,
    db_get_session_mentionable_users as db_get_session_mentionable_users,
    db_pin_session as db_pin_session,
    db_unpin_session as db_unpin_session,
    db_list_team_member_sids as db_list_team_member_sids,
    db_is_team_member as db_is_team_member,
    db_record_activity as db_record_activity,
    db_list_team_activity as db_list_team_activity,
)

# ── Comments ──────────────────────────────────────────────────────────────────
from .comments import (
    db_create_comment as db_create_comment,
    db_list_comments as db_list_comments,
    db_get_comment as db_get_comment,
    db_delete_comment as db_delete_comment,
    db_update_comment as db_update_comment,
    db_resolve_suggestion as db_resolve_suggestion,
    db_toggle_reaction as db_toggle_reaction,
    db_get_reactions_bulk as db_get_reactions_bulk,
)

# ── Notifications ─────────────────────────────────────────────────────────────
from .notifications import (
    db_create_notification as db_create_notification,
    db_list_notifications as db_list_notifications,
    db_mark_notification_read as db_mark_notification_read,
    db_mark_all_notifications_read as db_mark_all_notifications_read,
)

# ── Monitors ──────────────────────────────────────────────────────────────────
from .monitors import (
    db_create_monitor as db_create_monitor,
    db_list_monitors as db_list_monitors,
    db_delete_monitor as db_delete_monitor,
    db_get_monitor as db_get_monitor,
    db_update_monitor as db_update_monitor,
    db_list_monitor_runs as db_list_monitor_runs,
    db_get_due_monitors as db_get_due_monitors,
    db_update_monitor_run as db_update_monitor_run,
)

# ── Campaigns ─────────────────────────────────────────────────────────────────
from .campaigns import (
    db_create_campaign as db_create_campaign,
    db_list_campaigns as db_list_campaigns,
    db_get_campaign as db_get_campaign,
    db_update_campaign as db_update_campaign,
    db_delete_campaign as db_delete_campaign,
    db_clone_campaign as db_clone_campaign,
    db_cancel_job as db_cancel_job,
    db_get_due_campaigns as db_get_due_campaigns,
    db_update_campaign_next_run as db_update_campaign_next_run,
    db_get_campaign_stats as db_get_campaign_stats,
    db_import_entities as db_import_entities,
    db_import_attributes as db_import_attributes,
    db_export_campaign_results as db_export_campaign_results,
    db_transition_campaign_status as db_transition_campaign_status,
    db_get_campaign_status_audit as db_get_campaign_status_audit,
)

# ── Comparison ───────────────────────────────────────────────────────────────
from .comparison import db_compare_entities as db_compare_entities

# ── Entities ──────────────────────────────────────────────────────────────────
from .entities import (
    DuplicateLabelError as DuplicateLabelError,
    db_create_entity as db_create_entity,
    db_bulk_create_entities as db_bulk_create_entities,
    db_list_entities as db_list_entities,
    db_get_entity as db_get_entity,
    db_delete_entity as db_delete_entity,
    db_bulk_delete_entities as db_bulk_delete_entities,
    db_update_entity as db_update_entity,
    db_get_entity_metadata as db_get_entity_metadata,
    db_set_entity_metadata as db_set_entity_metadata,
    db_set_entity_metadata_batch as db_set_entity_metadata_batch,
    db_delete_entity_metadata as db_delete_entity_metadata,
    db_set_external_id as db_set_external_id,
    db_get_external_ids as db_get_external_ids,
    db_delete_external_id as db_delete_external_id,
    db_assign_entities_to_campaign as db_assign_entities_to_campaign,
    db_unassign_entities_from_campaign as db_unassign_entities_from_campaign,
)

# ── Attributes ────────────────────────────────────────────────────────────────
from .attributes import (
    db_create_attribute as db_create_attribute,
    db_bulk_create_attributes as db_bulk_create_attributes,
    db_list_attributes as db_list_attributes,
    db_get_attribute as db_get_attribute,
    db_update_attribute as db_update_attribute,
    db_delete_attribute as db_delete_attribute,
    db_bulk_delete_attributes as db_bulk_delete_attributes,
)

# ── Validation ────────────────────────────────────────────────────────────────
from .validation import (
    db_create_and_enqueue_validation_job as db_create_and_enqueue_validation_job,
    db_list_validation_jobs as db_list_validation_jobs,
    db_get_validation_job as db_get_validation_job,
    db_update_validation_job as db_update_validation_job,
    db_get_job_details as db_get_job_details,
    db_increment_job_progress as db_increment_job_progress,
    db_insert_result as db_insert_result,
    db_list_results as db_list_results,
    db_get_scores as db_get_scores,
    db_recompute_scores as db_recompute_scores,
    db_get_live_scores as db_get_live_scores,
    db_get_entity_cross_campaign as db_get_entity_cross_campaign,
    db_get_job_combined_report as db_get_job_combined_report,
    db_get_score_trends as db_get_score_trends,
    db_compare_jobs as db_compare_jobs,
    db_insert_results_batch as db_insert_results_batch,
)

# ── Knowledge ─────────────────────────────────────────────────────────────────
from .knowledge import (
    db_lookup_knowledge as db_lookup_knowledge,
    db_get_knowledge_for_campaign as db_get_knowledge_for_campaign,
    db_lookup_knowledge_batch as db_lookup_knowledge_batch,
    db_check_staleness_batch as db_check_staleness_batch,
)

# ── Knowledge Graph ───────────────────────────────────────────────────────────
from .knowledge_graph import (
    db_find_or_create_entity as db_find_or_create_entity,
    db_find_similar_entities as db_find_similar_entities,
    db_upsert_relationship as db_upsert_relationship,
    db_list_kg_entities as db_list_kg_entities,
    db_get_kg_entity as db_get_kg_entity,
    db_get_kg_relationship as db_get_kg_relationship,
    db_get_entity_relationships as db_get_entity_relationships,
    db_search_kg as db_search_kg,
    db_get_kg_stats as db_get_kg_stats,
    db_list_kg_conflicts as db_list_kg_conflicts,
    db_get_kg_graph as db_get_kg_graph,
    db_get_deal_partners as db_get_deal_partners,
    db_update_kg_entity as db_update_kg_entity,
    db_delete_kg_entity as db_delete_kg_entity,
    db_update_kg_relationship as db_update_kg_relationship,
    db_delete_kg_relationship as db_delete_kg_relationship,
    db_query_kg as db_query_kg,
    db_get_neighbors as db_get_neighbors,
)

# ── Templates ─────────────────────────────────────────────────────────────────
from .templates import (
    db_list_attribute_templates as db_list_attribute_templates,
    db_get_attribute_template as db_get_attribute_template,
    db_create_attribute_template as db_create_attribute_template,
    db_delete_attribute_template as db_delete_attribute_template,
    db_save_template_from_campaign as db_save_template_from_campaign,
    db_apply_template_to_campaign as db_apply_template_to_campaign,
)

# ── Library ───────────────────────────────────────────────────────────────────
from .library import (
    db_list_entity_library as db_list_entity_library,
    db_create_entity_library as db_create_entity_library,
    db_bulk_create_entity_library as db_bulk_create_entity_library,
    db_update_entity_library as db_update_entity_library,
    db_delete_entity_library as db_delete_entity_library,
    db_bulk_delete_library_entities as db_bulk_delete_library_entities,
    db_list_attribute_library as db_list_attribute_library,
    db_create_attribute_library as db_create_attribute_library,
    db_bulk_create_attribute_library as db_bulk_create_attribute_library,
    db_update_attribute_library as db_update_attribute_library,
    db_delete_attribute_library as db_delete_attribute_library,
    db_bulk_delete_library_attributes as db_bulk_delete_library_attributes,
    db_import_entities_from_library as db_import_entities_from_library,
    db_import_attributes_from_library as db_import_attributes_from_library,
)

# ── Programs ─────────────────────────────────────────────────────────────────
from .programs import (
    CampaignAlreadyAssignedError as CampaignAlreadyAssignedError,
    db_create_program as db_create_program,
    db_list_programs as db_list_programs,
    db_get_program as db_get_program,
    db_update_program as db_update_program,
    db_delete_program as db_delete_program,
    db_assign_campaign_to_program as db_assign_campaign_to_program,
    db_unassign_campaign_from_program as db_unassign_campaign_from_program,
    db_list_program_campaigns as db_list_program_campaigns,
)

# ── Scores ───────────────────────────────────────────────────────────────────
from .scores import (
    db_recalculate_scores as db_recalculate_scores,
    db_recalculate_scores_from_matrix as db_recalculate_scores_from_matrix,
    db_mark_scores_stale as db_mark_scores_stale,
    db_mark_scores_fresh as db_mark_scores_fresh,
    db_get_score as db_get_score,
    db_list_campaign_scores as db_list_campaign_scores,
)

# ── Clusters ─────────────────────────────────────────────────────────────────
from .clusters import (
    db_get_clusters as db_get_clusters,
    db_save_clusters as db_save_clusters,
    db_delete_clusters as db_delete_clusters,
)

# ── Matrix (entity-attribute cell values) ─────────────────────────────────────
from .matrix import (
    db_get_matrix_data as db_get_matrix_data,
    db_upsert_cell_value as db_upsert_cell_value,
    db_delete_cell_value as db_delete_cell_value,
    db_bulk_upsert_cells as db_bulk_upsert_cells,
)

# ── Campaign-Attribute Assignments ────────────────────────────────────────────
from .campaign_attributes import (
    db_assign_attribute_to_campaign as db_assign_attribute_to_campaign,
    db_update_campaign_attribute as db_update_campaign_attribute,
    db_unassign_attribute_from_campaign as db_unassign_attribute_from_campaign,
    db_get_campaign_attribute as db_get_campaign_attribute,
    db_list_campaign_attributes as db_list_campaign_attributes,
    db_reorder_campaign_attributes as db_reorder_campaign_attributes,
)

# ── Metadata Schemas ─────────────────────────────────────────────────────────
from .metadata_schemas import (
    db_create_metadata_schema as db_create_metadata_schema,
    db_list_metadata_schemas as db_list_metadata_schemas,
    db_get_metadata_schema as db_get_metadata_schema,
    db_update_metadata_schema as db_update_metadata_schema,
    db_delete_metadata_schema as db_delete_metadata_schema,
    db_bulk_create_metadata_schemas as db_bulk_create_metadata_schemas,
    db_reorder_metadata_schemas as db_reorder_metadata_schemas,
)

# ── Preferences ──────────────────────────────────────────────────────────────
from .preferences import (
    db_get_preferences as db_get_preferences,
    db_upsert_preferences as db_upsert_preferences,
)

# ── Client ID Lookup ─────────────────────────────────────────────────────────
from .client_lookup import (
    normalize_name as normalize_name,
    search_fuzzy_client as search_fuzzy_client,
    search_queue_client as search_queue_client,
)

# ── Research Jobs / Job Queue ─────────────────────────────────────────────────
from .jobs import (
    db_create_job as db_create_job,
    db_update_job as db_update_job,
    db_get_job as db_get_job,
    db_list_dead_jobs as db_list_dead_jobs,
    db_get_queue_job_owner as db_get_queue_job_owner,
    db_retry_dead_job as db_retry_dead_job,
)
