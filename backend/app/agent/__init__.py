# Import tools module to register @research_agent.tool decorators before any requests
from app.agent import tools as _tools  # noqa: F401

__all__ = ["_tools"]
