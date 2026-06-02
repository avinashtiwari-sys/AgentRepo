from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.notify import email
from config import REPS, EMPLOYEE_THRESHOLD

def _next_enterprise_rep(db: Session) -> dict:
    reps = REPS["enterprise"]
    rep_names = [r["name"] for r in reps]
    
    # Find the last enterprise lead that was routed
    last_lead = (
        db.query(Lead)
        .filter(Lead.assigned_rep.in_(rep_names))
        .order_by(Lead.updated_at.desc())
        .first()
    )
    
    if not last_lead or last_lead.assigned_rep not in rep_names:
        return reps[0]
        
    # Get the index of the last rep and pick the next one
    try:
        last_index = rep_names.index(last_lead.assigned_rep)
        next_index = (last_index + 1) % len(reps)
        return reps[next_index]
    except ValueError:
        return reps[0]


def run(lead: Lead, db: Session):
    """Route lead to correct rep based on employee count, then email the team."""
    enrichment = lead.enrichment_data or {}
    employee_count = enrichment.get("employee_count")

    # Determine segment and rep
    if employee_count is not None and employee_count > EMPLOYEE_THRESHOLD:
        segment = "Enterprise"
        rep = _next_enterprise_rep(db)
    else:
        segment = "SMB / Mid-Market"
        rep = REPS["smb"]

    lead.assigned_rep = rep["name"]
    lead.status = LeadStatus.ROUTED
    db.commit()

    print(f"[router] lead {lead.id} → {rep['name']} ({segment})")

    # Email alert to PcloudySalesMarketing@opkey.com
    lead_info = {
        "company": lead.company,
        "email": lead.email,
        "industry": enrichment.get("industry"),
        "employee_range": enrichment.get("employee_range"),
        "employee_count": employee_count,
        "confidence": enrichment.get("confidence"),
        "sources": enrichment.get("sources", []),
        "segment": segment,
        "received_at": lead.created_at,
    }
    email.send_lead_alert(lead.id, rep, lead_info)
