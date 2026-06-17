import hmac
from typing import List, Union, Optional
from fastapi import APIRouter, Request, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from models.lead import Lead, LeadStatus
from models.database import get_db
from config import ZOHO_WEBHOOK_SECRET
from app.logging_config import logger
from workers.queue import enqueue_pipeline

router = APIRouter()

class ZohoLeadPayload(BaseModel):
    contact_id: str
    contact_name: str
    email: EmailStr
    company: Optional[str] = ""
    lead_source: Optional[str] = ""
    # Optional: Zoho may send the shared secret in the body, but the
    # X-Zoho-Webhook-Token header is the preferred/ documented transport.
    token: Optional[str] = None

def _verify_token(token: Optional[str]) -> bool:
    """Constant-time comparison against the shared secret."""
    if not ZOHO_WEBHOOK_SECRET or not token:
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
    request: Request,
    db: Session = Depends(get_db),
):
    contacts_data = payload if isinstance(payload, list) else [payload]

    # Auth: prefer the X-Zoho-Webhook-Token header; fall back to a body token.
    header_token = request.headers.get("X-Zoho-Webhook-Token")
    body_token = contacts_data[0].token if contacts_data else None
    if not _verify_token(header_token or body_token):
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
            # Never persist the shared secret.
            raw_payload=contact.model_dump(exclude={"token"}),
        )
        db.add(lead)
        db.commit()

        logger.info(f"Accepted lead {zoho_id} from {contact.company}")
        enqueue_pipeline(zoho_id)
        accepted.append(zoho_id)

    return {"status": "accepted", "lead_ids": accepted}
