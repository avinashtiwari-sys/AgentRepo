from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger
from app.gates.base import mark_failed


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 2: company verifiable?
    Checks web presence exists and domain is not a competitor.
    Returns True to advance, False to mark invalid and stop.
    """
    web_presence = lead.enrichment.get("web_presence")
    is_competitor = lead.enrichment.get("is_competitor")
    sources = lead.enrichment.get("sources", [])

    logger.info(
        "[gate:verifier] lead_id=%s company=%s web_presence=%s is_competitor=%s sources=%s",
        lead.id, lead.company, web_presence, is_competitor, sources,
    )

    if not web_presence:
        mark_failed(lead, db, tag="verifier", status=LeadStatus.INVALID_COMPANY, reason="no web presence found")
        return False

    if is_competitor:
        mark_failed(lead, db, tag="verifier", status=LeadStatus.INVALID_COMPANY, reason="competitor domain")
        return False

    logger.info(
        "[gate:verifier] lead_id=%s company=%s — PASSED",
        lead.id, lead.company,
    )
    return True
