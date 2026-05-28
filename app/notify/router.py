from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.notify import email
from config import REPS, EMPLOYEE_THRESHOLD

# Mutable index for enterprise round-robin
_rr_index = {"value": 0}


def _next_enterprise_rep() -> dict:
    reps = REPS["enterprise"]
    rep = reps[_rr_index["value"] % len(reps)]
    _rr_index["value"] += 1
    return rep


def run(lead: Lead, db: Session):
    """Route lead to correct rep based on employee count, then email the team."""
    enrichment = lead.enrichment_data or {}
    employee_count = enrichment.get("employee_count")

    # Determine segment and rep
    if employee_count is not None and employee_count > EMPLOYEE_THRESHOLD:
        segment = "Enterprise"
        rep = _next_enterprise_rep()
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
        "segment": segment,
    }
    email.send_lead_alert(lead.id, rep, lead_info)
