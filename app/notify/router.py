from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.notify import email
from app.logging_config import logger

def run(lead: Lead, db: Session):
    """Notify the sales team of a new MQL."""
    # Generic assignment for all leads
    lead.assigned_rep = "Sales Team"
    lead.set_status(LeadStatus.ROUTED, db=db)

    logger.info(
        "[router] lead_id=%s company=%s industry=%s employee_range=%s confidence=%s assigned_rep=%s status=%s",
        lead.id, lead.company,
        lead.enrichment.get("industry"),
        lead.enrichment.get("employee_range"),
        lead.enrichment.get("confidence"),
        lead.assigned_rep,
        lead.status,
    )

    # Email alert
    lead_info = {
        "company": lead.company,
        "email": lead.email,
        "industry": lead.enrichment.get("industry"),
        "employee_range": lead.enrichment.get("employee_range"),
        "employee_count": lead.enrichment.get("employee_count"),
        "confidence": lead.enrichment.get("confidence"),
        "sources": lead.enrichment.get("sources", []),
        "segment": "All",
        "received_at": lead.created_at,
    }
    email.send_lead_alert(lead.id, {"name": "Sales Team"}, lead_info)

    logger.info(
        "[router] lead_id=%s — email alert sent to Sales Team",
        lead.id,
    )
