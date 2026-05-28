from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 2: company verifiable?
    Checks web presence exists and domain is not a competitor.
    Returns True to advance, False to mark invalid and stop.
    """
    enrichment = lead.enrichment_data or {}

    if not enrichment.get("web_presence"):
        _mark_invalid(lead, db, "no web presence found")
        return False

    if enrichment.get("is_competitor"):
        _mark_invalid(lead, db, "competitor domain")
        return False

    return True


def _mark_invalid(lead: Lead, db: Session, reason: str):
    lead.status = LeadStatus.INVALID_COMPANY
    lead.enrichment_data = {**lead.enrichment_data, "invalid_reason": reason}
    db.commit()
    print(f"[gate2] lead {lead.id} rejected — {reason}")
