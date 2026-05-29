import hmac
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, Depends
from sqlalchemy.orm import Session
from models.lead import Lead, LeadStatus
from models.database import get_db
from config import ZOHO_WEBHOOK_SECRET

router = APIRouter()


def _verify_token(token: str) -> bool:
    """Constant-time comparison against the shared secret configured in Zoho webhook settings."""
    return hmac.compare_digest(token, ZOHO_WEBHOOK_SECRET)


def _extract_domain(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


@router.post("/webhook/zoho")
async def zoho_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Token check — Zoho sends as query param e.g. ?X-Zoho-Webhook-Token=xxx
    if ZOHO_WEBHOOK_SECRET:
        token = request.query_params.get("X-Zoho-Webhook-Token", "")
        if not _verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()

    # Zoho sends a single object — wrap in list for uniform handling
    leads_data = payload if isinstance(payload, list) else [payload]

    accepted = []
    for lead_data in leads_data:
        # Match Zoho's actual field names from the webhook body
        zoho_id = lead_data.get("lead_id", "").strip()
        email   = lead_data.get("email", "").lower().strip()

        if not zoho_id or not email:
            continue

        # Dedup — skip if already received
        if db.query(Lead).filter(Lead.id == zoho_id).first():
            continue

        lead = Lead(
            id=zoho_id,
            email=email,
            first_name=lead_data.get("first_name", ""),
            last_name=lead_data.get("last_name", ""),
            company=lead_data.get("company", ""),
            domain=_extract_domain(email),
            lead_source=lead_data.get("lead_source", ""),
            status=LeadStatus.RECEIVED,
            raw_payload=lead_data,
        )
        db.add(lead)
        db.commit()

        # Schedule pipeline AFTER response is sent — Zoho gets 200 immediately
        background_tasks.add_task(_run_pipeline, zoho_id)
        accepted.append(zoho_id)

    return {"status": "accepted", "lead_ids": accepted}


def _run_pipeline(lead_id: str):
    from workers.pipeline import run_pipeline
    run_pipeline(lead_id)
