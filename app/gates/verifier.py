from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger


def _company_name_in_sources(company_name: str, sources: list) -> bool:
    """Check if the discovered company name appears in any source URL.

    This catches LLM hallucinations — if the enrichment claims the company is
    "Premiumlist Ltd" but none of the source URLs contain "premiumlist", the
    company name was likely fabricated from weak or unrelated search results.
    """
    if not company_name or not sources:
        return False

    name_lower = company_name.lower().strip()
    # Remove common suffixes for matching purposes
    for suffix in [" limited", " ltd", " inc", " llc", " corp", " corporation", ".", ","]:
        if name_lower.endswith(suffix):
            name_lower = name_lower[:len(name_lower)-len(suffix)]
    name_lower = name_lower.strip()

    # Extract meaningful tokens from the company name (words >= 4 chars)
    import re
    name_tokens = [t.lower() for t in re.findall(r'[a-zA-Z]{4,}', name_lower)]
    if not name_tokens:
        # If all tokens are short (e.g. "XYZ Corp"), use the whole cleaned name
        if len(name_lower) >= 3:
            name_tokens = [name_lower]
        else:
            return True  # can't meaningfully check, let it pass

    # Check each source URL — at least one token must appear in at least one URL
    for url in sources:
        url_lower = url.lower() if url else ""
        for token in name_tokens:
            if token in url_lower:
                return True

    return False


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 2: company verifier — strict.
    Rejects leads where AI enrichment found no web presence, the company
    is identified as a competitor, or the contact is flagged as spam/fake.
    Also catches LLM hallucinations by verifying the company name appears
    in at least one enrichment source URL.
    """
    web_presence = lead.enrichment.get("web_presence")
    is_competitor = lead.enrichment.get("is_competitor")
    is_spam = lead.enrichment.get("is_spam")
    sources = lead.enrichment.get("sources", [])
    company_name = (lead.enrichment.get("company_name") or "").strip()

    logger.info(
        "[gate:verifier] lead_id=%s company=%s web_presence=%s is_competitor=%s is_spam=%s sources=%s",
        lead.id, lead.company, web_presence, is_competitor, is_spam, sources,
    )

    # ── Reject spam / fake contacts ─────────────────────────────────
    if is_spam:
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s — REJECTED (flagged as spam or fake contact)",
            lead.id, lead.company,
        )
        lead.set_status(LeadStatus.INVALID_COMPANY, db=db)
        return False

    # ── Reject competitors ──────────────────────────────────────────
    if is_competitor:
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s — REJECTED (competitor)",
            lead.id, lead.company,
        )
        lead.set_status(LeadStatus.INVALID_COMPANY, db=db)
        return False

    # ── Weak web presence → REVIEW, don't drop ─────────────────────
    # The domain already passed Gate 1 (real business domain, MX + web check),
    # so a missing web_presence/sources here means the enrichment model could
    # not corroborate the company — not that the company is fake. Hard-rejecting
    # would silently lose genuine leads (e.g. real employees the model can't
    # find online), so route to human REVIEW instead.
    if not web_presence or not sources:
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s — REVIEW (enrichment found no web presence; needs manual check)",
            lead.id, lead.company,
        )
        lead.set_status(LeadStatus.REVIEW, db=db)
        return False

    # ── Source corroboration: company name must appear in sources ────
    # This catches LLM hallucinations where the model fabricates a company
    # name from unrelated search results (e.g. "Premiumlist Ltd" from results
    # about "platinumlist.net"). The enrichment may return a company name
    # that looks plausible but has zero support in the actual sources.
    if company_name and sources and not _company_name_in_sources(company_name, sources):
        logger.warning(
            "[gate:verifier] lead_id=%s company=%s domain=%s — REVIEW "
            "(company name '%s' not found in any source URL; possible LLM hallucination/impersonation)",
            lead.id, lead.company, lead.domain, company_name,
        )
        lead.set_status(LeadStatus.REVIEW, db=db)
        return False

    # ── Domain-company name sanity check ───────────────────────────
    # The resolved company name should relate to the domain.
    # e.g. "intecbusiness.co.uk" → "Intec Business Solutions" ✓
    if company_name:
        import difflib
        domain_lower = lead.domain.lower()
        domain_sld = domain_lower.split(".")[0]  # "intecbusiness" from "intecbusiness.co.uk"
        
        # Clean company name
        for suffix in [" limited", " ltd", " inc", " llc", " corp", " corporation"]:
            if company_name.lower().endswith(suffix):
                company_name = company_name[:len(company_name)-len(suffix)]
        company_norm = company_name.lower().strip()
        company_nospaces = company_norm.replace(" ", "")
        
        # 1. Exact match (ignoring spaces)
        is_exact = (domain_sld == company_nospaces)
        
        # 2. First word matches SLD exactly (e.g. "apple" == "apple")
        company_first = company_norm.split()[0] if company_norm.split() else ""
        is_first_word = (domain_sld == company_first and len(domain_sld) >= 3)
        
        # 3. Domain SLD is formed by first N words of company (e.g. "intecbusiness" == "intec" + "business")
        words = company_norm.split()
        is_word_combination = False
        prefix = ""
        for w in words:
            prefix += w
            if prefix == domain_sld:
                is_word_combination = True
                break
                
        # 4. Domain is acronym of the company (e.g. "ibm" for "international business machines")
        acronym = "".join([w[0] for w in company_norm.split() if w])
        is_acronym = (domain_sld == acronym and len(acronym) > 1)
        
        # 5. Very high string similarity (e.g. catches minor typos but rejects completely different words)
        similarity = difflib.SequenceMatcher(None, domain_sld, company_nospaces).ratio()
        is_highly_similar = similarity > 0.85

        if not (is_exact or is_first_word or is_word_combination or is_acronym or is_highly_similar):
            logger.warning(
                "[gate:verifier] lead_id=%s company=%s domain=%s — REVIEW (company name '%s' does not match domain; needs manual check)",
                lead.id, lead.company, lead.domain, company_name,
            )
            lead.set_status(LeadStatus.REVIEW, db=db)
            return False

    logger.info(
        "[gate:verifier] lead_id=%s company=%s — PASSED",
        lead.id, lead.company,
    )
    return True
