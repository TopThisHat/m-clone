"""
A2A Agent Card — defines the agent's capabilities for discovery.
"""
from a2a.types import AgentCard, AgentCapabilities, AgentSkill


def get_agent_card(host: str = "http://localhost:8000") -> AgentCard:
    return AgentCard(
        name="Playbook Research Agent",
        description=(
            "AI-powered research analyst that conducts thorough, multi-source research "
            "across web, financial data, SEC filings, Wikipedia, and uploaded documents."
        ),
        url=f"{host}/a2a",
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "text/markdown"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="research",
                name="Deep Research",
                description=(
                    "Conduct comprehensive research on any topic — finance, technology, "
                    "science, companies, markets — using web search, financial APIs, "
                    "SEC filings, Wikipedia, and uploaded documents."
                ),
                tags=["research", "analysis", "finance", "web-search"],
            ),
        ],
    )
