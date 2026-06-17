from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from alembic.config import Config
from alembic import command

from config import validate_config
from app.webhook import router as webhook_router
from app.logging_config import logger

BASE_DIR = Path(__file__).resolve().parent.parent


def _run_migrations():
    """Bring the database schema up to head. Idempotent and safe to run on
    every boot — Alembic is the single source of truth for the schema."""
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast on missing required config before accepting any traffic.
    warnings = validate_config()
    for name in warnings:
        logger.warning(f"Optional config missing: {name} — related feature disabled")

    _run_migrations()
    logger.info("GTMFlow application started")
    yield


app = FastAPI(title="GTMFlow", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
def health():
    return {"status": "ok"}
