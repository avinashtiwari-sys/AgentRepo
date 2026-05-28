from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 3: confidence high or med?
    Low confidence leads go to human review queue.
    Returns True to advance, False to park in review.
    """
    confidence = (lead.enrichment_data or {}).get("confidence", "low")

    if confidence == "low":
        lead.status = LeadStatus.REVIEW
        db.commit()
        print(f"[gate3] lead {lead.id} → human review queue (confidence=low)")
        return False

    return True
