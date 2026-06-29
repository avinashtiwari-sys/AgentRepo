from sqlalchemy import Column, String, DateTime, JSON
from datetime import datetime
from models.lead import Base


class CompanyEnrichment(Base):
    """Domain-keyed cache of company-level enrichment.

    Company facts (name, size, industry, web presence, sources) do not change
    per contact, so they are cached here and reused across every lead from the
    same domain. Only the per-person lookup runs fresh for each lead.
    """
    __tablename__ = "company_enrichment"

    domain = Column(String, primary_key=True)
    data = Column(JSON, default=dict)   # company-level enrichment fields only
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
