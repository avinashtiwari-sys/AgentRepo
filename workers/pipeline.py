from models.database import SessionLocal
from models.lead import Lead, LeadStatus
from app.gates import domain, verifier, confidence
from app.enrichment import agent
from app.notify import router as notify_router
from app.logging_config import logger


def run_pipeline(lead_id: str):
    """Entry point for the RQ worker. Runs all pipeline stages for a lead."""
    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            logger.warning("pipeline received unknown lead_id=%s", lead_id)
            return

        logger.info(
            "[pipeline] lead_id=%s company=%s domain=%s email=%s source=%s status=%s — entering pipeline",
            lead.id, lead.company, lead.domain, lead.email, lead.lead_source, lead.status,
        )

        # Reject Apollo-sourced leads — no enrichment, no routing
        if lead.lead_source and lead.lead_source.strip().lower() == "apollo":
            lead.set_status(LeadStatus.SKIPPED, db=db)
            logger.warning(
                "[pipeline] lead_id=%s company=%s email=%s source=%s — REJECTED (Apollo-sourced leads are not processed)",
                lead.id, lead.company, lead.email, lead.lead_source,
            )
            return

        # Gate 1 — domain valid?
        if not domain.run(lead, db):
            return

        # Phase 3 — AI enrichment
        logger.info(
            "[pipeline] lead_id=%s company=%s domain=%s — starting AI enrichment",
            lead.id, lead.company, lead.domain,
        )
        enrichment = agent.run(lead.company, lead.domain)
        lead.enrichment_data = enrichment
        lead.set_status(LeadStatus.ENRICHING, db=db)
        logger.info(
            "[pipeline] lead_id=%s enriched — confidence=%s employees=%s industry=%s web_presence=%s is_competitor=%s sources=%s",
            lead.id,
            enrichment.get("confidence"),
            enrichment.get("employee_count"),
            enrichment.get("industry"),
            enrichment.get("web_presence"),
            enrichment.get("is_competitor"),
            enrichment.get("sources", []),
        )

        # Gate 2 — company verifiable?
        if not verifier.run(lead, db):
            return

        # Gate 3 — confidence high/med?
        if not confidence.run(lead, db):
            return

        # Mark MQL valid
        lead.set_status(LeadStatus.MQL_VALID, db=db)
        logger.info(
            "[pipeline] lead_id=%s company=%s — MQL_VALID, proceeding to routing",
            lead.id, lead.company,
        )

        # Phase 5 — route and notify
        notify_router.run(lead, db)

        logger.info(
            "[pipeline] lead_id=%s company=%s status=%s assigned_rep=%s — pipeline complete",
            lead.id, lead.company, lead.status, lead.assigned_rep,
        )

    except Exception:
        logger.exception("[pipeline] lead_id=%s — unhandled exception in pipeline", lead_id)

    finally:
        db.close()
