from models.database import SessionLocal
from models.lead import Lead, LeadStatus
from app.enrichment import agent
from app.notify import email


def run_pipeline(lead_id: str):
    db = SessionLocal()
    try:
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return

        if lead.lead_source and lead.lead_source.strip().lower() == "apollo":
            lead.status = LeadStatus.SKIPPED
            db.commit()
            print(f"[pipeline] {lead_id} skipped (Apollo)")
            return

        enrichment = {}
        if lead.company and lead.domain:
            print(f"[pipeline] {lead_id} enriching {lead.company}")
            enrichment = agent.run(lead.company, lead.domain)
            lead.enrichment_data = enrichment
            profiles = enrichment.get("profiles", [])
            print(f"[pipeline] {lead_id} enriched — confidence={enrichment.get('confidence', '?')}, "
                  f"profiles={enrichment.get('profile_count', 0)}")

        lead.assigned_rep = "Sales Team"
        lead.status = LeadStatus.ROUTED
        db.commit()

        email.send_lead_alert(lead.id, {"name": "Sales Team"}, {
            "company": lead.company,
            "email": lead.email,
            "industry": enrichment.get("industry"),
            "employee_range": enrichment.get("employee_range"),
            "employee_count": enrichment.get("employee_count"),
            "confidence": enrichment.get("confidence"),
            "sources": enrichment.get("sources", []),
            "profiles": enrichment.get("profiles", []),
            "profile_count": enrichment.get("profile_count", 0),
            "segment": "All",
            "received_at": lead.created_at,
        })

    finally:
        db.close()
