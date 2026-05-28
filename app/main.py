from fastapi import FastAPI
from app.webhook import router as webhook_router
from models.database import init_db

app = FastAPI(title="GTMFlow", version="0.1.0")

@app.on_event("startup")
def startup():
    init_db()

app.include_router(webhook_router)

@app.get("/health")
def health():
    return {"status": "ok"}
