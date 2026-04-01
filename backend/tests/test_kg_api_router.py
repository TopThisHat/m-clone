"""Tests for KG API Router: Simplified Team Access and New Endpoints (m-clone-8n5n).

Covers:
  - 6.1-6.2: _resolve_team_access returns str, master team gate
  - 6.3: Endpoints no longer pass include_master
  - 6.4: GET /api/kg/master-team-id (no auth)
  - 6.5: POST /api/kg/entities/{entity_id}/promote
  - 6.6: POST /api/kg/entities/{entity_id}/sync-from-master
  - 6.7: POST /api/kg/entities/merge
  - 6.8: GET /api/kg/entities/flags
  - 6.9: PATCH /api/kg/entities/flags/{flag_id}
  - 6.10: GET /api/kg/entities/{entity_id} passes team_id
  - 7.1-7.3: include_master removed from AgentDeps and get_agent_deps
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.dependencies import AgentDeps, get_agent_deps
from app.routers.knowledge_graph import _resolve_team_access

MASTER_TEAM_ID = settings.kg_master_team_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user(sid: str = "user-1") -> dict[str, Any]:
    return {"sub": sid}


# ---------------------------------------------------------------------------
# 6.1-6.2: _resolve_team_access
# ---------------------------------------------------------------------------

class TestResolveTeamAccess:
    """Simplified _resolve_team_access returns a str, never a tuple."""

    @pytest.mark.asyncio
    async def test_returns_str(self):
        """Return type is str, not tuple."""
        team_id = str(uuid.uuid4())
        with (
            patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=False)),
            patch("app.routers.knowledge_graph.db_is_team_member", AsyncMock(return_value=True)),
        ):
            result = await _resolve_team_access(_user(), team_id)
        assert isinstance(result, str)
        assert result == team_id

    @pytest.mark.asyncio
    async def test_master_team_requires_super_admin(self):
        """Passing the master team id requires super admin.  Non-SA gets 403."""
        from fastapi import HTTPException

        with patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=False)):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_team_access(_user(), MASTER_TEAM_ID)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_master_team_allowed_for_super_admin(self):
        """Super admin can access the master team id."""
        with patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=True)):
            result = await _resolve_team_access(_user(), MASTER_TEAM_ID)
        assert result == MASTER_TEAM_ID

    @pytest.mark.asyncio
    async def test_non_member_gets_403(self):
        from fastapi import HTTPException

        team_id = str(uuid.uuid4())
        with (
            patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=False)),
            patch("app.routers.knowledge_graph.db_is_team_member", AsyncMock(return_value=False)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_team_access(_user(), team_id)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_auto_resolve_first_team(self):
        """No team_id supplied resolves to user's first team."""
        first_team = str(uuid.uuid4())
        with (
            patch("app.routers.knowledge_graph.db_list_user_teams", AsyncMock(return_value=[{"id": first_team}, {"id": str(uuid.uuid4())}])),
        ):
            result = await _resolve_team_access(_user(), None)
        assert result == first_team

    @pytest.mark.asyncio
    async def test_no_teams_403(self):
        """User with no teams and no team_id gets 403."""
        from fastapi import HTTPException

        with patch("app.routers.knowledge_graph.db_list_user_teams", AsyncMock(return_value=[])):
            with pytest.raises(HTTPException) as exc_info:
                await _resolve_team_access(_user(), None)
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_super_admin_bypasses_membership_check(self):
        """Super admin can access any team without membership."""
        team_id = str(uuid.uuid4())
        with (
            patch("app.routers.knowledge_graph.db_is_super_admin", AsyncMock(return_value=True)),
        ):
            # db_is_team_member is NOT patched -- should not be called
            result = await _resolve_team_access(_user(), team_id)
        assert result == team_id


# ---------------------------------------------------------------------------
# 6.4: GET /api/kg/master-team-id
# ---------------------------------------------------------------------------

class TestMasterTeamIdEndpoint:

    @pytest.mark.asyncio
    async def test_returns_master_team_id(self):
        from app.routers.knowledge_graph import get_master_team_id

        result = await get_master_team_id()
        assert result == {"team_id": MASTER_TEAM_ID}


# ---------------------------------------------------------------------------
# 7.1-7.3: include_master removed from AgentDeps and get_agent_deps
# ---------------------------------------------------------------------------

class TestAgentDepsNoIncludeMaster:

    def test_no_include_master_field(self):
        """AgentDeps should not have an include_master field."""
        assert not hasattr(AgentDeps, "include_master") or "include_master" not in AgentDeps.__dataclass_fields__

    def test_get_agent_deps_no_include_master_param(self):
        """get_agent_deps should not accept include_master parameter."""
        import inspect
        sig = inspect.signature(get_agent_deps)
        assert "include_master" not in sig.parameters

    def test_get_agent_deps_still_works(self):
        """get_agent_deps produces valid AgentDeps without include_master."""
        deps = get_agent_deps(team_ids=["t1", "t2"])
        assert deps.team_ids == ["t1", "t2"]

    def test_defaults_team_ids_empty(self):
        deps = get_agent_deps()
        assert deps.team_ids == []


# ---------------------------------------------------------------------------
# 6.5-6.9: New endpoint handlers (unit tests via direct function calls)
# ---------------------------------------------------------------------------

class TestPromoteEndpoint:

    @pytest.mark.asyncio
    async def test_promote_success(self):
        from app.routers.knowledge_graph import promote_entity

        entity_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        master_id = str(uuid.uuid4())

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value=team_id)),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_promote_entity_to_master", AsyncMock(return_value=master_id)),
        ):
            result = await promote_entity(entity_id=entity_id, team_id=team_id, user=_user())

        assert result == {"master_entity_id": master_id}

    @pytest.mark.asyncio
    async def test_promote_not_found(self):
        from fastapi import HTTPException
        from app.routers.knowledge_graph import promote_entity

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value="t1")),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_promote_entity_to_master", AsyncMock(return_value=None)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await promote_entity(entity_id="x", team_id="t1", user=_user())
            assert exc_info.value.status_code == 404


class TestSyncFromMasterEndpoint:

    @pytest.mark.asyncio
    async def test_sync_success(self):
        from app.routers.knowledge_graph import sync_entity_from_master

        entity_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        synced = {"id": entity_id, "name": "synced"}

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value=team_id)),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_get_kg_entity", AsyncMock(return_value={"id": entity_id})),
            patch("app.routers.knowledge_graph.db_sync_entity_from_master", AsyncMock(return_value=synced)),
        ):
            result = await sync_entity_from_master(entity_id=entity_id, team_id=team_id, user=_user())

        assert result["name"] == "synced"

    @pytest.mark.asyncio
    async def test_sync_no_master_link(self):
        from fastapi import HTTPException
        from app.routers.knowledge_graph import sync_entity_from_master

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value="t1")),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_get_kg_entity", AsyncMock(return_value={"id": "x"})),
            patch("app.routers.knowledge_graph.db_sync_entity_from_master", AsyncMock(return_value=None)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await sync_entity_from_master(entity_id="x", team_id="t1", user=_user())
            assert exc_info.value.status_code == 400


class TestMergeEndpoint:

    @pytest.mark.asyncio
    async def test_merge_success(self):
        from app.routers.knowledge_graph import merge_entities, MergeEntitiesRequest

        team_id = str(uuid.uuid4())
        winner = {"id": "w", "name": "winner"}
        body = MergeEntitiesRequest(winner_id="w", loser_id="l", team_id=team_id)

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value=team_id)),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_merge_kg_entities", AsyncMock(return_value=winner)),
        ):
            result = await merge_entities(body=body, user=_user())

        assert result["name"] == "winner"

    @pytest.mark.asyncio
    async def test_merge_cross_team_fails(self):
        from fastapi import HTTPException
        from app.routers.knowledge_graph import merge_entities, MergeEntitiesRequest

        body = MergeEntitiesRequest(winner_id="w", loser_id="l", team_id="t1")

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value="t1")),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_merge_kg_entities", AsyncMock(return_value=None)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await merge_entities(body=body, user=_user())
            assert exc_info.value.status_code == 400


class TestEntityFlagsEndpoint:

    @pytest.mark.asyncio
    async def test_list_flags(self):
        from app.routers.knowledge_graph import list_entity_flags

        team_id = str(uuid.uuid4())
        flags = [{"id": "f1", "entity_id": "e1", "reason": "dup"}]

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value=team_id)),
            patch("app.routers.knowledge_graph.db_list_entity_flags", AsyncMock(return_value=flags)),
        ):
            result = await list_entity_flags(team_id=team_id, user=_user())

        assert len(result) == 1
        assert result[0]["reason"] == "dup"


class TestResolveFlagEndpoint:

    @pytest.mark.asyncio
    async def test_resolve_flag_success(self):
        from app.routers.knowledge_graph import resolve_flag, FlagPatch

        body = FlagPatch(resolved=True)
        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value="t1")),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_resolve_entity_flag", AsyncMock(return_value=True)),
        ):
            result = await resolve_flag(flag_id="f1", body=body, team_id="t1", user=_user())

        assert result == {"resolved": True}

    @pytest.mark.asyncio
    async def test_resolve_flag_not_found(self):
        from fastapi import HTTPException
        from app.routers.knowledge_graph import resolve_flag, FlagPatch

        body = FlagPatch(resolved=True)
        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value="t1")),
            patch("app.routers.knowledge_graph._require_kg_edit", AsyncMock()),
            patch("app.routers.knowledge_graph.db_resolve_entity_flag", AsyncMock(return_value=False)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await resolve_flag(flag_id="f-none", body=body, team_id="t1", user=_user())
            assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# 6.10: GET /api/kg/entities/{entity_id} passes team_id
# ---------------------------------------------------------------------------

class TestGetEntityTeamAccess:

    @pytest.mark.asyncio
    async def test_entity_team_verified(self):
        from app.routers.knowledge_graph import get_entity

        team_id = str(uuid.uuid4())
        entity = {"id": "e1", "name": "Foo", "team_id": team_id}

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value=team_id)),
            patch("app.routers.knowledge_graph.db_get_kg_entity", AsyncMock(return_value=entity)),
        ):
            result = await get_entity(entity_id="e1", team_id=team_id, user=_user())

        assert result["name"] == "Foo"

    @pytest.mark.asyncio
    async def test_entity_wrong_team_403(self):
        from fastapi import HTTPException
        from app.routers.knowledge_graph import get_entity

        team_id = str(uuid.uuid4())
        other_team = str(uuid.uuid4())
        entity = {"id": "e1", "name": "Foo", "team_id": other_team}

        with (
            patch("app.routers.knowledge_graph._resolve_team_access", AsyncMock(return_value=team_id)),
            patch("app.routers.knowledge_graph.db_get_kg_entity", AsyncMock(return_value=entity)),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_entity(entity_id="e1", team_id=team_id, user=_user())
            assert exc_info.value.status_code == 403
