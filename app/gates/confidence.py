from models.lead import Lead
from sqlalchemy.orm import Session
from app.logging_config import logger


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 3: confidence score.
    Logs the confidence level but always passes.
    """
    confidence = lead.enrichment.get("confidence", "low")
    sources = lead.enrichment.get("sources", [])

    logger.info(
        "[gate:confidence] lead_id=%s company=%s confidence=%s sources=%s",
        lead.id, lead.company, confidence, sources,
    )

    if confidence == "low":
        logger.warning(
            "[gate:confidence] lead_id=%s company=%s confidence=%s — low confidence, continuing pipeline",
            lead.id, lead.company, confidence,
        )
    else:
        logger.info(
            "[gate:confidence] lead_id=%s company=%s confidence=%s — PASSED",
            lead.id, lead.company, confidence,
        )
    return True
