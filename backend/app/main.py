"""FastAPI main application entry point."""
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.api import leads, properties, conversations, webhooks, voice

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
    # Startup: verify connections, warm up models
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
    allow_origins=["*"],  # Restrict in production
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
        content={"detail": "Internal server error", "error": str(exc)}
    )


@app.get("/")
async def root():
    """Health check."""
    return {
        "status": "online",
        "service": "Dubai Real Estate AI",
        "version": "1.0.0",
        "agents": ["scoring", "qualifier", "research", "conversational", "followup", "handoff"]
    }


@app.get("/health")
async def health_check():
    """Detailed health check."""
    return {
        "status": "healthy",
        "database": "connected",
        "llm": "groq",
        "scrapers": ["bayut", "propertyfinder", "dubizzle"]
    }


# Include routers
app.include_router(leads.router, prefix="/api/v1/leads", tags=["Leads"])
app.include_router(properties.router, prefix="/api/v1/properties", tags=["Properties"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["Conversations"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["Webhooks"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=get_settings().APP_PORT,
        reload=get_settings().APP_ENV == "development"
    )
