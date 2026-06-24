from sqlalchemy import Column, String, DateTime, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class LeadStatus(str, enum.Enum):
    RECEIVED = "received"
    ENRICHING = "enriching"
    MQL_VALID = "mql_valid"
    ROUTED = "routed"
    SKIPPED = "skipped"
    INVALID_DOMAIN = "invalid_domain"
    INVALID_COMPANY = "invalid_company"
    REVIEW = "review"


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String, primary_key=True)          # Zoho lead ID
    email = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    company = Column(String)
    domain = Column(String)
    lead_source = Column(String)
    # Stored as a plain string (not a DB-native enum) so new statuses don't
    # require an ALTER TYPE migration. LeadStatus is a str-enum, so assigning
    # a member stores its value (e.g. "mql_valid").
    status = Column(String, default=LeadStatus.RECEIVED.value, nullable=False)
    enrichment_data = Column(JSON, default=dict)   # size, industry, confidence, sources
    assigned_rep = Column(String)
    raw_payload = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def enrichment(self) -> dict:
        """Return enrichment_data or an empty dict — never None."""
        return self.enrichment_data or {}

    def set_status(self, new_status: LeadStatus, *, db):
        """Transition to a new status and commit."""
        self.status = new_status
        db.commit()
