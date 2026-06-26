import dns.resolver
import httpx
from functools import lru_cache
from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger
from config import TAVILY_API_KEY

# Common free/disposable email providers
BLOCKED_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com",
    "proton.me", "tutanota.com", "guerrillamail.com", "mailinator.com",
    "tempmail.com", "throwaway.email", "yopmail.com", "sharklasers.com",
    "trashmail.com", "dispostable.com", "fakeinbox.com", "getairmail.com",
    "maildrop.cc", "spamgourmet.com", "10minutemail.com", "temp-mail.org",
}


@lru_cache(maxsize=1024)
def _has_mx_record(domain: str) -> bool:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=5)
        return len(answers) > 0
    except Exception:
        return False


@lru_cache(maxsize=1024)
def _quick_web_check(domain: str) -> bool:
    """Quick Tavily search to see if the domain belongs to a known company."""
    if not TAVILY_API_KEY:
        logger.warning("[gate:domain] TAVILY_API_KEY not set — skipping web check for %s", domain)
        return True  # can't verify, let it pass to avoid false rejections
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": f'{domain}',
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])

        if not results:
            logger.info("[gate:domain] domain=%s — no web results found", domain)
            return False

        # Check if any result's URL or content mentions this domain
        domain_lower = domain.lower()
        sld = domain_lower.split(".")[0]  # "intecbusiness" from "intecbusiness.co.uk"

        for r in results:
            url = (r.get("url") or "").lower()
            content = (r.get("content") or "").lower()
            title = (r.get("title") or "").lower()
            full_text = f"{url} {content} {title}"

            if domain_lower in full_text:
                return True
            # Also check if the SLD appears in the results (catches parent companies)
            if len(sld) >= 4 and sld in full_text:
                return True

        # Results exist but nothing matches — suspicious
        logger.info("[gate:domain] domain=%s — %d web results found but none reference the domain", domain, len(results))
        return False
    except Exception as e:
        logger.warning("[gate:domain] web check failed for %s: %s", domain, str(e)[:80])
        return True  # on error, let it pass


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 1: strict domain verification.
    Rejects leads that fail domain checks — no personal or throwaway domains.
    """
    logger.info(
        "[gate:domain] lead_id=%s checking domain=%s",
        lead.id, lead.domain,
    )

    if not lead.domain:
        logger.warning(
            "[gate:domain] lead_id=%s — REJECTED (no domain extracted from email)",
            lead.id,
        )
        lead.set_status(LeadStatus.INVALID_DOMAIN, db=db)
        return False

    domain_lower = lead.domain.lower()

    # ── Strict reject: personal / free email domains ────────────────
    if domain_lower in BLOCKED_DOMAINS:
        logger.warning(
            "[gate:domain] lead_id=%s domain=%s — REJECTED (free/personal email domain)",
            lead.id, domain_lower,
        )
        lead.set_status(LeadStatus.INVALID_DOMAIN, db=db)
        return False

    # ── Strict reject: no MX record → not a real business domain ────
    if not _has_mx_record(domain_lower):
        logger.warning(
            "[gate:domain] lead_id=%s domain=%s — REJECTED (no MX record — not a valid business domain)",
            lead.id, domain_lower,
        )
        lead.set_status(LeadStatus.INVALID_DOMAIN, db=db)
        return False

    # ── Web lookup: confirm domain belongs to a real company ────────
    if not _quick_web_check(domain_lower):
        logger.warning(
            "[gate:domain] lead_id=%s domain=%s — REJECTED (web lookup could not confirm this is a real company domain)",
            lead.id, domain_lower,
        )
        lead.set_status(LeadStatus.INVALID_DOMAIN, db=db)
        return False

    logger.info(
        "[gate:domain] lead_id=%s domain=%s — PASSED",
        lead.id, domain_lower,
    )
    return True
