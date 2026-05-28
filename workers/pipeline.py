from models.database import SessionLocal
from models.lead import Lead, LeadStatus
from app.gates import domain, verifier, confidence
from app.enrichment import agent
from app.crm import zoho
from app.notify import router as notify_router


def run_pipeline(lead_id: str):
    """Entry point for the RQ worker. Runs all pipeline stages for a lead."""
    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return

        # Gate 1 — domain valid?
        if not domain.run(lead, db):
            return

        # Phase 3 — AI enrichment
        print(f"[pipeline] lead {lead_id} — enriching {lead.company} ({lead.domain})")
        enrichment = agent.run(lead.company, lead.domain)
        lead.enrichment_data = enrichment
        lead.status = LeadStatus.ENRICHING
        db.commit()
        print(f"[pipeline] lead {lead_id} enriched — confidence={enrichment['confidence']}, employees={enrichment['employee_count']}")

        # Gate 2 — company verifiable?
        if not verifier.run(lead, db):
            return

        # Gate 3 — confidence high/med?
        if not confidence.run(lead, db):
            return

        # Mark MQL valid
        lead.status = LeadStatus.MQL_VALID
        db.commit()
        print(f"[pipeline] lead {lead_id} — MQL valid")

        # Phase 5 — route and notify
        notify_router.run(lead, db)

    finally:
        db.close()
