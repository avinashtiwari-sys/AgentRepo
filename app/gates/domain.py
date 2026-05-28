import dns.resolver
from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session

# Common free/disposable email providers
BLOCKED_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com",
    "proton.me", "tutanota.com", "guerrillamail.com", "mailinator.com",
    "tempmail.com", "throwaway.email", "yopmail.com", "sharklasers.com",
    "trashmail.com", "dispostable.com", "fakeinbox.com", "getairmail.com",
    "maildrop.cc", "spamgourmet.com", "10minutemail.com", "temp-mail.org",
}


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
    domain = lead.domain

    if not domain:
        _mark_invalid(lead, db, "no domain")
        return False

    if domain in BLOCKED_DOMAINS:
        _mark_invalid(lead, db, f"free/disposable domain: {domain}")
        return False

    if not _has_mx_record(domain):
        _mark_invalid(lead, db, f"no MX record: {domain}")
        return False

    return True


def _mark_invalid(lead: Lead, db: Session, reason: str):
    lead.status = LeadStatus.INVALID_DOMAIN
    lead.enrichment_data = {**lead.enrichment_data, "invalid_reason": reason}
    db.commit()
    print(f"[gate1] lead {lead.id} rejected — {reason}")
