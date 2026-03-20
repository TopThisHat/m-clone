"""
A2A AgentExecutor — bridges the ResearchOrchestrator into Google's A2A protocol.
"""
from __future__ import annotations

import logging
from typing import Any

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    Artifact,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from a2a.utils import new_agent_text_message

from app.agent.agent import (
    FinalResult,
    ResearchOrchestrator,
    TextDelta,
    ToolCallStart,
    ToolResult,
)
from app.dependencies import AgentDeps, get_agent_deps

logger = logging.getLogger(__name__)


class ResearchAgentExecutor(AgentExecutor):
    """Execute research queries via A2A protocol."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Extract query from the A2A context
        query = ""
        task = context.current_task
        if task and task.history:
            for msg in reversed(task.history):
                for part in msg.parts:
                    if hasattr(part, "text"):
                        query = part.text
                        break
                if query:
                    break

        if not query:
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    status=TaskStatus(state=TaskState.failed),
                    final=True,
                )
            )
            return

        deps = get_agent_deps()
        orchestrator = ResearchOrchestrator()

        # Emit working status
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(
                    state=TaskState.working,
                    message=new_agent_text_message(f"Researching: {query}"),
                ),
            )
        )

        final_text = ""

        async for event in orchestrator.run(query, deps):
            if isinstance(event, TextDelta):
                final_text += event.token

            elif isinstance(event, ToolCallStart):
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(
                            state=TaskState.working,
                            message=new_agent_text_message(
                                f"Using tool: {event.name}"
                            ),
                        ),
                    )
                )

            elif isinstance(event, FinalResult):
                final_text = event.text or final_text

                await event_queue.enqueue_event(
                    TaskArtifactUpdateEvent(
                        artifact=Artifact(
                            parts=[TextPart(text=final_text)],
                            name="Research Report",
                        ),
                    )
                )

                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        status=TaskStatus(state=TaskState.completed),
                        final=True,
                    )
                )
                return

        # If we get here without a FinalResult, mark completed with whatever we have
        if final_text:
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    artifact=Artifact(
                        parts=[TextPart(text=final_text)],
                        name="Research Report",
                    ),
                )
            )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.completed),
                final=True,
            )
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                status=TaskStatus(state=TaskState.canceled),
                final=True,
            )
        )
