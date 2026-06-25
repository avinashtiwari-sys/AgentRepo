import dns.resolver
from functools import lru_cache
from models.lead import Lead
from sqlalchemy.orm import Session
from app.logging_config import logger

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
    Gate 1: domain check.
    Logs findings but always passes — no lead is rejected here.
    """
    logger.info(
        "[gate:domain] lead_id=%s checking domain=%s",
        lead.id, lead.domain,
    )

    issues = []
    if not lead.domain:
        issues.append("no domain")
    elif lead.domain.lower() in BLOCKED_DOMAINS:
        issues.append(f"free/disposable domain: {lead.domain}")
    elif not _has_mx_record(lead.domain):
        issues.append(f"no MX record: {lead.domain}")

    if issues:
        logger.warning(
            "[gate:domain] lead_id=%s domain=%s — issues found: %s — continuing pipeline",
            lead.id, lead.domain, "; ".join(issues),
        )
    else:
        logger.info(
            "[gate:domain] lead_id=%s domain=%s — PASSED",
            lead.id, lead.domain,
        )
    return True
