from models.lead import Lead
from sqlalchemy.orm import Session
from app.logging_config import logger


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 2: company verifier.
    Logs web presence and competitor findings but always passes.
    """
    web_presence = lead.enrichment.get("web_presence")
    is_competitor = lead.enrichment.get("is_competitor")
    sources = lead.enrichment.get("sources", [])

    logger.info(
        "[gate:verifier] lead_id=%s company=%s web_presence=%s is_competitor=%s sources=%s",
        lead.id, lead.company, web_presence, is_competitor, sources,
    )

    issues = []
    if not web_presence:
        issues.append("no web presence found")
    if is_competitor:
        issues.append("competitor domain")

    if issues:
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s — issues found: %s — continuing pipeline",
            lead.id, lead.company, "; ".join(issues),
        )
    else:
        logger.info(
            "[gate:verifier] lead_id=%s company=%s — PASSED",
            lead.id, lead.company,
        )
    return True
