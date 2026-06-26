from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 2: company verifier — strict.
    Rejects leads where AI enrichment found no web presence or the company
    is identified as a competitor.
    """
    web_presence = lead.enrichment.get("web_presence")
    is_competitor = lead.enrichment.get("is_competitor")
    sources = lead.enrichment.get("sources", [])

    logger.info(
        "[gate:verifier] lead_id=%s company=%s web_presence=%s is_competitor=%s sources=%s",
        lead.id, lead.company, web_presence, is_competitor, sources,
    )

    # ── Reject competitors ──────────────────────────────────────────
    if is_competitor:
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s — REJECTED (competitor)",
            lead.id, lead.company,
        )
        lead.set_status(LeadStatus.INVALID_COMPANY, db=db)
        return False

    # ── Reject leads with no discoverable web presence ──────────────
    if not web_presence or not sources:
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s — REJECTED (no web presence found)",
            lead.id, lead.company,
        )
        lead.set_status(LeadStatus.INVALID_COMPANY, db=db)
        return False

    # ── Domain-company name sanity check ───────────────────────────
    # The resolved company name should relate to the domain.
    # e.g. "intecbusiness.co.uk" → "Intec Business Solutions" ✓
    #      "gluak.com"          → "Glu Mobile"              ✗ (hallucination)
    _MIN_MATCH = 4
    company_name = (lead.enrichment.get("company_name") or "").strip()
    if company_name:
        domain_lower = lead.domain.lower()
        domain_sld = domain_lower.split(".")[0]  # "intecbusiness" from "intecbusiness.co.uk"
        company_norm = company_name.lower().replace("limited", "").replace("ltd", "").replace("inc", "").replace("llc", "").strip()
        company_first = company_norm.split()[0] if company_norm.split() else ""

        # Check mutual substring containment with minimum length
        sld_in_company = len(domain_sld) >= _MIN_MATCH and domain_sld in company_norm
        company_in_sld = len(company_first) >= _MIN_MATCH and company_first in domain_lower
        company_in_domain = len(company_norm) >= _MIN_MATCH and company_norm in domain_lower

        if not (sld_in_company or company_in_sld or company_in_domain):
            logger.warning(
                "[gate:verifier] lead_id=%s company=%s domain=%s — REJECTED (company name '%s' does not match domain)",
                lead.id, lead.company, lead.domain, company_name,
            )
            lead.set_status(LeadStatus.INVALID_COMPANY, db=db)
            return False

    logger.info(
        "[gate:verifier] lead_id=%s company=%s — PASSED",
        lead.id, lead.company,
    )
    return True
