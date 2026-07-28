import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from alembic.config import Config
from alembic import command
from sqlalchemy import text
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import sentry_sdk

from config import validate_config, DATABASE_URL, REDIS_URL, MODE, SENTRY_DSN
from app.webhook import router as webhook_router
from app.logging_config import logger
from app.limits import limiter
from models.database import SessionLocal
from workers.queue import redis_conn

BASE_DIR = Path(__file__).resolve().parent.parent
_start_time = time.time()

# ── Sentry ──────────────────────────────────────────────────────────────
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=MODE,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )
    logger.info("Sentry error tracking initialized")
else:
    logger.info("Sentry DSN not set — error tracking disabled")


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
    logger.info("GTMFlow application shutting down")


def _check_db() -> dict:
    """Verify database connectivity with a simple query."""
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return {"status": "up", "url": _sanitize_url(DATABASE_URL)}
    except Exception as e:
        return {"status": "down", "error": str(e)}


def _check_redis() -> dict:
    """Verify Redis connectivity with PING."""
    try:
        redis_conn.ping()
        info = redis_conn.info("server")
        return {
            "status": "up",
            "url": _sanitize_url(REDIS_URL),
            "version": info.get("redis_version", "unknown"),
        }
    except Exception as e:
        return {"status": "down", "error": str(e)}


def _sanitize_url(url: str) -> str:
    """Strip credentials from a connection URL for safe logging."""
    if "@" in url:
        scheme_rest, _ = url.rsplit("@", 1)
        scheme = scheme_rest.split("://")[0] if "://" in scheme_rest else scheme_rest
        return f"{scheme}://***@{url.rsplit('@', 1)[-1]}"
    return url


app = FastAPI(title="GTMFlow", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(webhook_router)


@app.get("/health")
@limiter.exempt
def health(request: Request):
    db = _check_db()
    redis = _check_redis()

    all_up = db["status"] == "up" and redis["status"] == "up"

    return JSONResponse(
        status_code=200 if all_up else 503,
        content={
            "status": "ok" if all_up else "degraded",
            "version": "0.1.0",
            "mode": MODE,
            "uptime_seconds": int(time.time() - _start_time),
            "components": {
                "database": db,
                "redis": redis,
            },
        },
    )
