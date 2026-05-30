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


def _parse_name(contact_name: str):
    """Split 'First Last' into first and last name."""
    parts = contact_name.strip().split(" ", 1)
    first = parts[0] if len(parts) > 0 else ""
    last  = parts[1] if len(parts) > 1 else ""
    return first, last


@router.post("/webhook/zoho")
async def zoho_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    payload = await request.json()

    # Token check — read from JSON body (Zoho strips query params in raw JSON mode)
    if ZOHO_WEBHOOK_SECRET:
        contacts_data = payload if isinstance(payload, list) else [payload]
        token = contacts_data[0].get("token", "") if contacts_data else ""
        if not _verify_token(token):
            raise HTTPException(status_code=401, detail="Invalid token")

    # Zoho sends a single object — wrap in list for uniform handling
    contacts_data = payload if isinstance(payload, list) else [payload]

    accepted = []
    for contact in contacts_data:
        zoho_id = contact.get("contact_id", "").strip()
        email   = contact.get("email", "").lower().strip()

        if not zoho_id or not email:
            print(f"[webhook] skipped — missing contact_id or email: {contact}")
            continue

        # Dedup — skip if already received
        if db.query(Lead).filter(Lead.id == zoho_id).first():
            print(f"[webhook] duplicate — {zoho_id} already exists")
            continue

        first_name, last_name = _parse_name(contact.get("contact_name", ""))

        lead = Lead(
            id=zoho_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            company=contact.get("company", ""),
            domain=_extract_domain(email),
            lead_source=contact.get("lead_source", ""),
            status=LeadStatus.RECEIVED,
            raw_payload=contact,
        )
        db.add(lead)
        db.commit()

        # Schedule pipeline AFTER response is sent — Zoho gets 200 immediately
        background_tasks.add_task(_run_pipeline, zoho_id)
        accepted.append(zoho_id)

    return {"status": "accepted", "lead_ids": accepted}


def _run_pipeline(lead_id: str):
    try:
        from workers.pipeline import run_pipeline
        run_pipeline(lead_id)
    except Exception as e:
        import traceback
        print(f"[pipeline] ERROR for lead {lead_id}: {e}")
        print(traceback.format_exc())
