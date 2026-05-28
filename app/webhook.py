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
    # Token check — skip in dev if secret not set
    if ZOHO_WEBHOOK_SECRET:
        token = request.headers.get("X-Zoho-Webhook-Token", "")
        if not _verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()
    leads_data = payload.get("leads", [payload])  # handle both list and single

    accepted = []
    for lead_data in leads_data:
        zoho_id = lead_data.get("id") or lead_data.get("Id")
        email = lead_data.get("Email", "").lower().strip()

        if not zoho_id or not email:
            continue

        # Dedup — skip if already received
        if db.query(Lead).filter(Lead.id == zoho_id).first():
            continue

        lead = Lead(
            id=zoho_id,
            email=email,
            first_name=lead_data.get("First_Name", ""),
            last_name=lead_data.get("Last_Name", ""),
            company=lead_data.get("Company", ""),
            domain=_extract_domain(email),
            lead_source=lead_data.get("Lead_Source", ""),
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
