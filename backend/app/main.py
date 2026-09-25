"""FastAPI main application entry point."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.modules.ops.health import deep_health
from app.modules.store import load_demo_scale
from app.api import (
    admin,
    auth,
    billing,
    broker,
    conversations,
    dashboard,
    ingest,
    ingestion,
    leads,
    market,
    members,
    properties,
    voice,
    webhooks,
    workflows,
    workspace,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, get_settings().LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("🚀 Dubai Real Estate AI Platform starting...")
    counts = load_demo_scale()
    if counts:
        logger.info("demo scale data loaded: %s", counts)
    yield
    # Shutdown: cleanup
    logger.info("👋 Shutting down...")


app = FastAPI(
    title="Dubai Real Estate AI Lead Generation Platform",
    description="Multi-agent AI system for real estate lead generation, qualification, and closing",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global error handler."""
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal_error", "message": "Internal server error"}}
    )


@app.get("/")
async def root():
    """Health check."""
    return {
        "status": "online",
        "service": "Dubai Real Estate AI",
        "version": "1.0.0",
        "engine": ["extractor", "policy", "scorer", "responder", "guard", "handoff"]
    }


@app.get("/health")
async def health_check():
    """Dependency configuration health without exposing credentials.

    Also reports the effective data mode per source, so it's always obvious
    whether a deployment is serving seeded demo data or talking to a real
    service. ``configured`` vs ``mock`` here is the difference between a live
    customer instance and a demo.
    """
    settings = get_settings()
    return {
        "status": "healthy",
        "workspace": settings.WORKSPACE_NAME,
        "tenancy": "single-tenant",
        "database": "configured" if settings.SUPABASE_URL else "mock",
        "redis": "configured" if settings.REDIS_URL else "missing",
        "llm": "configured" if settings.GROQ_API_KEY else "fallback",
        "billing": "configured" if settings.STRIPE_SECRET_KEY else "disabled",
        "data_modes": {
            "properties": settings.properties_mode,
            "whatsapp": settings.whatsapp_mode,
            "dld": settings.DATA_MODE_DLD,
        },
        "voice_outbound": (
            "enabled" if settings.VOICE_OUTBOUND_ENABLED else "disabled"
        ),
    }


@app.get("/health/deep")
async def health_deep():
    """Time-boxed probes of the datastore, Redis and LLM breakers (architecture §12)."""
    report = await deep_health(get_settings().WORKSPACE_ID)
    return JSONResponse(report, status_code=503 if report["status"] == "unhealthy" else 200)


# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Auth"])
app.include_router(members.router, prefix="/api/v1/members", tags=["Members"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(leads.router, prefix="/api/v1/leads", tags=["Leads"])
app.include_router(properties.router, prefix="/api/v1/properties", tags=["Properties"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["Conversations"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])
app.include_router(workspace.router, prefix="/api/v1/workspace", tags=["Workspace"])
app.include_router(ingestion.router, prefix="/api/v1/ingestion", tags=["Ingestion"])
app.include_router(ingest.router, prefix="/api/v1/ingest", tags=["Ingest"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin"])
app.include_router(broker.router, prefix="/api/v1/broker", tags=["Broker"])
app.include_router(billing.router, prefix="/api/v1/billing", tags=["Billing"])
app.include_router(market.router, prefix="/api/v1/market", tags=["Market"])
app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["Workflows"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=get_settings().APP_PORT,
        reload=get_settings().APP_ENV == "development"
    )
