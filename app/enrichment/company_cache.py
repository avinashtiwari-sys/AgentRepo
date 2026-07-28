"""Domain-keyed cache for company-level enrichment.

Company facts are identical for every contact at the same domain, so we cache
them and reuse them across leads instead of re-running the LLM/web research each
time. Per-person fields (``profiles``) are never cached — they are looked up
fresh for each lead.
"""
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models.company import CompanyEnrichment
from config import COMPANY_CACHE_TTL_DAYS
from app.logging_config import logger

# Company-level fields that are safe to share across contacts at the same domain.
COMPANY_FIELDS = (
    "company_name", "employee_count", "employee_range", "industry",
    "web_presence", "is_competitor", "sources", "confidence",
)


def get_fresh(domain: str, db: Session) -> dict | None:
    """Return cached company-level fields for the domain if still fresh, else None."""
    if not domain or COMPANY_CACHE_TTL_DAYS <= 0:
        return None
    row = db.query(CompanyEnrichment).filter(CompanyEnrichment.domain == domain).first()
    if not row or not row.data:
        return None
    age = datetime.utcnow() - (row.updated_at or datetime.utcnow())
    if age > timedelta(days=COMPANY_CACHE_TTL_DAYS):
        logger.info("[company_cache] domain=%s — cache stale (%s old), refreshing", domain, age)
        return None
    logger.info("[company_cache] domain=%s — cache HIT (%s old)", domain, age)
    return dict(row.data)


def upsert(domain: str, enrichment: dict, db: Session) -> None:
    """Store/refresh the company-level slice of an enrichment result for a domain."""
    if not domain or COMPANY_CACHE_TTL_DAYS <= 0:
        return
    # Only cache when the enrichment actually found the company — never cache a
    # failed/empty lookup, or we would poison the cache for a real company.
    if not enrichment.get("web_presence") or not enrichment.get("sources"):
        return
    company_slice = {k: enrichment.get(k) for k in COMPANY_FIELDS}
    row = db.query(CompanyEnrichment).filter(CompanyEnrichment.domain == domain).first()
    if row:
        row.data = company_slice
        row.updated_at = datetime.utcnow()
    else:
        db.add(CompanyEnrichment(domain=domain, data=company_slice, updated_at=datetime.utcnow()))
    db.commit()
    logger.info("[company_cache] domain=%s — cache updated", domain)
