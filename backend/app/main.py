# Load .env into environment BEFORE any module-level instantiation
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_pool, init_schema
from app import scheduler
from app.routers import documents, research, sessions, usage
from app.routers.sessions import router_public
from app.routers.auth import router as auth_router
from app.routers.teams import router as teams_router
from app.routers.comments import router as comments_router
from app.routers.notifications import router as notifications_router
from app.routers.monitors import router as monitors_router
from app.routers.campaigns import router as campaigns_router
from app.routers.entities import router as entities_router
from app.routers.attributes import router as attributes_router
from app.routers.jobs import router as jobs_router
from app.routers.templates import router as templates_router
from app.routers.library import router as library_router
from app.routers.knowledge_graph import router as kg_router
from app.routers.programs import router as programs_router

app = FastAPI(
    title="m-clone Research Agent",
    description="Deep research agent powered by GPT-4o with A2A interoperability",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(research.router)
app.include_router(documents.router)
app.include_router(sessions.router)
app.include_router(router_public)
app.include_router(usage.router)
app.include_router(teams_router)
app.include_router(comments_router)
app.include_router(notifications_router)
app.include_router(monitors_router)
app.include_router(campaigns_router)
app.include_router(entities_router)
app.include_router(attributes_router)
app.include_router(jobs_router)
app.include_router(templates_router)
app.include_router(library_router)
app.include_router(kg_router)
app.include_router(programs_router)

# ── A2A Protocol ─────────────────────────────────────────────────────────────
from a2a.server.apps.jsonrpc.fastapi_app import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

from app.agent.a2a_card import get_agent_card
from app.agent.a2a_executor import ResearchAgentExecutor

_task_store = InMemoryTaskStore()
_a2a_handler = DefaultRequestHandler(
    agent_executor=ResearchAgentExecutor(),
    task_store=_task_store,
)
_a2a_app = A2AFastAPIApplication(
    agent_card=get_agent_card(),
    http_handler=_a2a_handler,
)
_a2a_app.add_routes_to_app(
    app,
    agent_card_url="/.well-known/a2a/agent-card",
    rpc_url="/a2a",
)


@app.on_event("startup")
async def startup():
    if (
        settings.jwt_secret == "change-me-in-prod"
        and not settings.dev_auth_bypass
    ):
        raise RuntimeError(
            "JWT_SECRET is set to the insecure default. "
            "Set a strong JWT_SECRET or enable DEV_AUTH_BYPASS=true for local dev."
        )

    if settings.database_url or settings.aws_secret_name:
        await init_schema()
    scheduler.start()

    if settings.aws_mode:
        from app import openai_factory
        openai_factory.initialize()


@app.on_event("shutdown")
async def shutdown():
    scheduler.stop()
    await close_pool()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
