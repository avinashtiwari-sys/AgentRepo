import hmac
from typing import List, Union, Optional
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from models.lead import Lead, LeadStatus
from models.database import get_db
from config import ZOHO_WEBHOOK_SECRET
from app.logging_config import logger

router = APIRouter()

class ZohoLeadPayload(BaseModel):
    token: str
    contact_id: str
    contact_name: str
    email: EmailStr
    company: Optional[str] = ""
    lead_source: Optional[str] = ""

def _verify_token(token: str) -> bool:
    """Constant-time comparison against the shared secret."""
    if not ZOHO_WEBHOOK_SECRET:
        return False
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
    payload: Union[ZohoLeadPayload, List[ZohoLeadPayload]],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Enforce token check
    contacts_data = payload if isinstance(payload, list) else [payload]
    
    if not contacts_data or not _verify_token(contacts_data[0].token):
        logger.warning("Rejected webhook: Invalid or missing token")
        raise HTTPException(status_code=401, detail="Invalid or missing webhook token")

    accepted = []
    for contact in contacts_data:
        zoho_id = contact.contact_id.strip()
        email   = contact.email.lower().strip()

        if db.query(Lead).filter(Lead.id == zoho_id).first():
            logger.info(f"Skipping duplicate lead: {zoho_id}")
            continue

        first_name, last_name = _parse_name(contact.contact_name)

        lead = Lead(
            id=zoho_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            company=contact.company,
            domain=_extract_domain(email),
            lead_source=contact.lead_source,
            status=LeadStatus.RECEIVED,
            raw_payload=contact.model_dump(),
        )
        db.add(lead)
        db.commit()

        logger.info(f"Accepted lead {zoho_id} from {contact.company}")
        background_tasks.add_task(_run_pipeline, zoho_id)
        accepted.append(zoho_id)

    return {"status": "accepted", "lead_ids": accepted}

def _run_pipeline(lead_id: str):
    try:
        from workers.pipeline import run_pipeline
        run_pipeline(lead_id)
    except Exception as e:
        logger.error(f"Pipeline failure for lead {lead_id}: {e}", exc_info=True)
