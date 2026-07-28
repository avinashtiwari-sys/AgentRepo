from models.database import SessionLocal
from models.lead import Lead, LeadStatus
from app.gates import domain, verifier, confidence
from app.enrichment import agent
from app.enrichment import company_cache
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
        if lead.lead_source and "apollo" in lead.lead_source.strip().lower():
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
        contact_name = f"{lead.first_name} {lead.last_name}".strip() or lead.email.split("@")[0]
        # Reuse cached company facts for this domain if still fresh; only the
        # per-person lookup runs anew.
        cached_company = company_cache.get_fresh(lead.domain, db)
        enrichment = agent.run(
            lead.domain, lead.domain,
            contact_name=contact_name, email=lead.email,
            company_context=cached_company,
        )
        lead.enrichment_data = enrichment
        lead.set_status(LeadStatus.ENRICHING, db=db)

        # Refresh the domain cache when this was a fresh (uncached) lookup.
        if not cached_company:
            company_cache.upsert(lead.domain, enrichment, db)

        # If Zoho didn't provide a company name, fill it from enrichment
        if not lead.company or lead.company.strip() == "":
            discovered = enrichment.get("company_name", "").strip()
            if discovered:
                lead.company = discovered
                logger.info(
                    "[pipeline] lead_id=%s — company resolved from enrichment: '%s'",
                    lead.id, discovered,
                )

        logger.info(
            "[pipeline] lead_id=%s enriched — company=%s confidence=%s employees=%s industry=%s web_presence=%s is_competitor=%s sources=%s",
            lead.id,
            lead.company,
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
        # Log, flag the lead for review, then re-raise so RQ records the failure
        # and applies its retry/backoff policy. Swallowing here would mark the job
        # "succeeded" and defeat retries + the dead-letter (FailedJobRegistry).
        logger.exception("[pipeline] lead_id=%s — unhandled exception in pipeline", lead_id)
        try:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead and lead.status not in (
                LeadStatus.MQL_VALID, LeadStatus.ROUTED,
                LeadStatus.INVALID_DOMAIN, LeadStatus.INVALID_COMPANY,
            ):
                lead.set_status(LeadStatus.REVIEW, db=db)
        except Exception:
            logger.exception("[pipeline] lead_id=%s — could not flag lead for review", lead_id)
        raise

    finally:
        db.close()
