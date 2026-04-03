"""Feature flags for gradual multi-mode agent rollout.

Controls the percentage of traffic that uses automatic mode classification
versus the legacy RESEARCH-only path.  Setting ``AUTO_MODE_ROLLOUT_PERCENT``
to 0 (the default) disables auto-classification entirely — all requests fall
back to the legacy ``stream_research()`` code path.

Usage:
    from app.agent.feature_flags import should_use_auto_mode

    if should_use_auto_mode(user_sid=ctx.user_sid):
        # Use stream_agent() with auto classification
        ...
    else:
        # Use legacy stream_research()
        ...
"""
from __future__ import annotations

import hashlib

from app.config import settings


def should_use_auto_mode(user_sid: str | None = None) -> bool:
    """Determine if auto classification should be used for this request.

    When ``auto_mode_rollout_percent`` is 0 (default), all requests use
    legacy RESEARCH mode.  When 100, all requests use auto classification.
    For values in between, routes based on a consistent hash of
    ``user_sid`` so that the same user always gets the same behavior
    within a given rollout percentage.

    Args:
        user_sid: The authenticated user's SID.  When ``None`` and the
            rollout percentage is between 1-99, the request falls back
            to legacy mode (conservative default).

    Returns:
        ``True`` if the request should use auto mode classification,
        ``False`` if it should use legacy RESEARCH mode.
    """
    percent = settings.auto_mode_rollout_percent
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    if not user_sid:
        return False
    # Consistent hashing so same user always gets same behavior
    h = int(hashlib.md5(user_sid.encode()).hexdigest(), 16)
    return (h % 100) < percent
