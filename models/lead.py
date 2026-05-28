from sqlalchemy import Column, String, Integer, DateTime, Enum, JSON
from sqlalchemy.orm import declarative_base
from datetime import datetime
import enum

Base = declarative_base()


class LeadStatus(str, enum.Enum):
    RECEIVED = "received"
    INVALID_DOMAIN = "invalid_domain"
    ENRICHING = "enriching"
    INVALID_COMPANY = "invalid_company"
    REVIEW = "review"
    MQL_VALID = "mql_valid"
    ROUTED = "routed"


class Lead(Base):
    __tablename__ = "leads"

    id = Column(String, primary_key=True)          # Zoho lead ID
    email = Column(String, nullable=False)
    first_name = Column(String)
    last_name = Column(String)
    company = Column(String)
    domain = Column(String)
    lead_source = Column(String)
    status = Column(Enum(LeadStatus), default=LeadStatus.RECEIVED)
    enrichment_data = Column(JSON, default=dict)   # size, industry, confidence
    assigned_rep = Column(String)
    raw_payload = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
