import dns.resolver
from functools import lru_cache
from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger
from app.gates.base import mark_failed

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


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 1: domain valid?
    Returns True to advance, False to mark invalid and stop.
    """
    logger.info(
        "[gate:domain] lead_id=%s checking domain=%s",
        lead.id, lead.domain,
    )

    if not lead.domain:
        mark_failed(lead, db, tag="domain", status=LeadStatus.INVALID_DOMAIN, reason="no domain")
        return False

    if lead.domain.lower() in BLOCKED_DOMAINS:
        mark_failed(lead, db, tag="domain", status=LeadStatus.INVALID_DOMAIN, reason=f"free/disposable domain: {lead.domain}")
        return False

    if not _has_mx_record(lead.domain):
        mark_failed(lead, db, tag="domain", status=LeadStatus.INVALID_DOMAIN, reason=f"no MX record: {lead.domain}")
        return False

    logger.info(
        "[gate:domain] lead_id=%s domain=%s — PASSED",
        lead.id, lead.domain,
    )
    return True
