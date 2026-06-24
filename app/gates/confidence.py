from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 3: confidence high or med?
    Low confidence leads go to human review queue.
    Returns True to advance, False to park in review.
    """
    confidence = lead.enrichment.get("confidence", "low")
    sources = lead.enrichment.get("sources", [])

    logger.info(
        "[gate:confidence] lead_id=%s company=%s confidence=%s sources=%s",
        lead.id, lead.company, confidence, sources,
    )

    if confidence == "low":
        lead.set_status(LeadStatus.REVIEW, db=db)
        logger.warning(
            "[gate:confidence] lead_id=%s company=%s — REVIEW (confidence=low) status=%s",
            lead.id, lead.company, lead.status,
        )
        return False

    logger.info(
        "[gate:confidence] lead_id=%s company=%s confidence=%s — PASSED",
        lead.id, lead.company, confidence,
    )
    return True
