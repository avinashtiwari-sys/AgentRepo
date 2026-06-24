"""Shared gate utilities."""
from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger


def mark_failed(
    lead: Lead,
    db: Session,
    *,
    status: LeadStatus,
    tag: str,
    reason: str,
) -> None:
    """Reject a lead at a gate with a reason and log the event."""
    lead.status = status
    lead.enrichment_data = {**lead.enrichment, "invalid_reason": reason}
    db.commit()
    logger.warning(
        "[gate:%s] lead_id=%s company=%s — REJECTED reason=%s status=%s",
        tag, lead.id, lead.company, reason, lead.status,
    )
