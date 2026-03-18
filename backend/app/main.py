# Load .env into environment BEFORE any module-level Agent instantiation
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import app.agent  # noqa: F401 — registers @research_agent.tool decorators
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

app = FastAPI(
    title="m-clone Research Agent",
    description="Deep research agent powered by GPT-4o and pydantic-ai",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("DEBUG: Including auth_router")
app.include_router(auth_router)
print("DEBUG: Including research.router")
app.include_router(research.router)
print("DEBUG: Including documents.router")
app.include_router(documents.router)
print("DEBUG: Including sessions.router")
app.include_router(sessions.router)
print("DEBUG: Including router_public")
app.include_router(router_public)
print("DEBUG: Including usage.router")
app.include_router(usage.router)
print("DEBUG: Including teams_router")
app.include_router(teams_router)
print("DEBUG: Including comments_router")
app.include_router(comments_router)
print("DEBUG: Including notifications_router")
app.include_router(notifications_router)
print("DEBUG: Including monitors_router")
app.include_router(monitors_router)
print("DEBUG: Including campaigns_router")
app.include_router(campaigns_router)
print("DEBUG: Including entities_router")
app.include_router(entities_router)
print("DEBUG: Including attributes_router")
app.include_router(attributes_router)
print("DEBUG: Including jobs_router")
app.include_router(jobs_router)
print("DEBUG: Including templates_router")
app.include_router(templates_router)
print("DEBUG: Including library_router")
app.include_router(library_router)
print("DEBUG: Including kg_router")
app.include_router(kg_router)
print("DEBUG: All routers included")


@app.on_event("startup")
async def startup():
    print("DEBUG: startup event called")
    # Skip init_schema for now - schema should already exist
    # if settings.database_url or settings.aws_secret_name:
    #     await init_schema()
    print("DEBUG: about to call scheduler.start()")
    scheduler.start()
    print("DEBUG: scheduler.start() completed")


@app.on_event("shutdown")
async def shutdown():
    scheduler.stop()
    await close_pool()


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
