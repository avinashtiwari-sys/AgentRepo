from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.notify import email

def run(lead: Lead, db: Session):
    """Notify the sales team of a new MQL."""
    enrichment = lead.enrichment_data or {}
    
    # Generic assignment for all leads
    lead.assigned_rep = "Sales Team"
    lead.status = LeadStatus.ROUTED
    db.commit()

    print(f"[router] lead {lead.id} → Sales Team")

    # Email alert
    lead_info = {
        "company": lead.company,
        "email": lead.email,
        "industry": enrichment.get("industry"),
        "employee_range": enrichment.get("employee_range"),
        "employee_count": enrichment.get("employee_count"),
        "confidence": enrichment.get("confidence"),
        "sources": enrichment.get("sources", []),
        "segment": "All",
        "received_at": lead.created_at,
    }
    email.send_lead_alert(lead.id, {"name": "Sales Team"}, lead_info)
