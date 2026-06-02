from fastapi import FastAPI
from app.webhook import router as webhook_router
from models.database import init_db
from app.logging_config import logger

app = FastAPI(title="GTMFlow", version="0.1.0")

@app.on_event("startup")
def startup():
    init_db()
    logger.info("GTMFlow application started")

app.include_router(webhook_router)

@app.get("/health")
def health():
    return {"status": "ok"}
