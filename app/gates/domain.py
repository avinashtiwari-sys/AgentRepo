import re
import dns.resolver
import httpx
from functools import lru_cache
from models.lead import Lead, LeadStatus
from sqlalchemy.orm import Session
from app.logging_config import logger
from config import TAVILY_API_KEY

# Sequences used to detect keyboard-mashed local-parts (asdf, qwerty, zxcv…).
_KEYBOARD_WALKS = (
    "qwertyuiop", "asdfghjkl", "zxcvbnm", "1234567890",
    "qazwsxedcrfv", "qwerty", "azerty", "qwertz",
)
_VOWELS = set("aeiou")

# Generic / role mailboxes — an organisation address, not a real individual client.
# These are "anonymous": there is no genuine person behind them to qualify as a lead.
_ROLE_ACCOUNTS = {
    "info", "sales", "contact", "support", "admin", "administrator", "hello",
    "help", "helpdesk", "noreply", "no-reply", "donotreply", "do-not-reply",
    "office", "team", "marketing", "enquiry", "enquiries", "inquiry", "inquiries",
    "billing", "accounts", "accounting", "hr", "careers", "jobs", "recruitment",
    "webmaster", "postmaster", "mail", "email", "general", "feedback", "service",
    "services", "newsletter", "press", "media", "legal", "abuse", "security",
}


def _is_role_account(local_part: str) -> bool:
    """Is the local-part a generic/role mailbox rather than an individual person?"""
    lp = (local_part or "").strip().lower().split("+")[0]
    return lp in _ROLE_ACCOUNTS


# Second-level labels used under country-code TLDs (co.uk, gov.sg, co.th, edu.kg…).
# Used to find the registrable label rather than naively taking the first segment.
_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac", "go", "or", "ne", "gob", "mil"}


def _registrable_label(domain: str) -> str:
    """Return the registrable label of a domain, handling multi-part TLDs.

    nac.gov.sg -> "nac", intecbusiness.co.uk -> "intecbusiness",
    mail.google.com -> "google", meta.com -> "meta".
    """
    parts = (domain or "").lower().split(".")
    if len(parts) <= 2:
        return parts[0] if parts else ""
    if parts[-2] in _SECOND_LEVEL and len(parts) >= 3:
        return parts[-3]
    return parts[-2]


def _looks_auto_generated(local_part: str) -> bool:
    """Heuristic: does the email local-part (before the @) look auto-generated/fake?

    Deliberately conservative so it never flags real names — handles like
    "haobo.xing", "vidyasagar.gummadi", "kazelyn_ko", "siphekahle" must all pass.
    It only fires on unmistakable junk: keyboard walks ("asdf"), word+number
    generators ("duskstag783", "fbn990"), high digit-ratio strings ("mh3782a"),
    and vowel-less gibberish.
    """
    lp = (local_part or "").strip().lower()
    if not lp:
        return True

    # Drop any "+tag" suffix; keep the meaningful handle.
    lp = lp.split("+")[0]
    letters = re.sub(r"[^a-z]", "", lp)        # alphabetic core
    compact = re.sub(r"[^a-z0-9]", "", lp)     # letters + digits, no separators

    # 1. Keyboard walk (asdf, qwerty, zxcv, …)
    if len(letters) >= 4:
        for seq in _KEYBOARD_WALKS:
            if letters in seq or letters[::-1] in seq:
                return True

    # 2. Word followed by 3+ trailing digits → generator pattern
    #    (duskstag783, brightfalcon1872, pinknewt118, fbn990, cauch55398)
    if re.search(r"[a-z]\d{3,}$", compact):
        return True

    # 3. High digit ratio in a reasonably long handle (random alphanumerics: mh3782a)
    digits = sum(c.isdigit() for c in compact)
    if len(compact) >= 5 and digits / len(compact) >= 0.5:
        return True

    # 4. No vowels at all in a letters-only handle of length >= 4 (gibberish)
    if len(letters) >= 4 and letters == compact and not (set(letters) & _VOWELS):
        return True

    return False


# Common free/disposable email providers
BLOCKED_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "protonmail.com",
    "proton.me", "tutanota.com", "guerrillamail.com", "mailinator.com",
    "tempmail.com", "throwaway.email", "yopmail.com", "sharklasers.com",
    "trashmail.com", "dispostable.com", "fakeinbox.com", "getairmail.com",
    "maildrop.cc", "spamgourmet.com", "10minutemail.com", "temp-mail.org",
    "fommie.com", "dustmail.net", "preoweb.net", "skatingion.com", 
    "minitts.net", "my.com", "cccwata.space"
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
        sld = _registrable_label(domain_lower)  # "nac" from "nac.gov.sg"

        for r in results:
            url = (r.get("url") or "").lower()
            content = (r.get("content") or "").lower()
            title = (r.get("title") or "").lower()
            full_text = f"{url} {content} {title}"

            if domain_lower in full_text:
                return True
            # Longer labels are distinctive enough to match anywhere in the result.
            if len(sld) >= 4 and sld in full_text:
                return True
            # Short labels (e.g. "nac") are too generic to match free text, but a
            # hit inside the result URL/host is a reliable signal.
            if len(sld) == 3 and sld in url:
                return True

        # Results exist but nothing matches — suspicious
        logger.info("[gate:domain] domain=%s — %d web results found but none reference the domain", domain, len(results))
        return False
    except Exception as e:
        logger.warning("[gate:domain] web check failed for %s: %s", domain, str(e)[:80])
        return True  # on error, let it pass


# TLDs disproportionately used for throwaway / spam signups. Not an automatic
# reject (many are legitimate) — used as a tie-breaker signal.
_SUSPICIOUS_TLDS = {
    "space", "click", "link", "icu", "top", "monster", "rest", "fit", "buzz",
    "cam", "work", "gq", "cf", "ml", "tk", "ga", "online", "site", "website",
}


def _suspicious_tld(domain: str) -> bool:
    """Is the domain's TLD one commonly abused for throwaway signups?"""
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""
    return tld in _SUSPICIOUS_TLDS


@lru_cache(maxsize=1024)
def _website_reachable(domain: str) -> bool:
    """Does the domain serve a live website (HTTP < 500 on https or http)?"""
    for scheme in ("https://", "http://"):
        try:
            resp = httpx.get(
                scheme + domain,
                timeout=8,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; gtmflow/1.0)"},
            )
            if resp.status_code < 500:
                return True
        except Exception:
            continue
    return False


def _looks_like_name(local_part: str) -> bool:
    """Does the local-part resemble a human name (john, john.doe, j.doe)?"""
    lp = (local_part or "").strip().lower().split("+")[0]
    tokens = [t for t in re.split(r"[._-]+", lp) if t]
    if not tokens or len(tokens) > 3:
        return False
    # All tokens alphabetic, no digits, at least one token >= 2 chars.
    return (
        all(t.isalpha() for t in tokens)
        and any(len(t) >= 2 for t in tokens)
    )


def _matches_lead_name(local_part: str, first_name: str, last_name: str) -> bool:
    """Does the local-part align with the name the CRM provided for the lead?"""
    lp = re.sub(r"[^a-z]", "", (local_part or "").lower())
    fn = (first_name or "").strip().lower()
    ln = (last_name or "").strip().lower()
    if not lp or not (fn or ln):
        return False
    if fn and len(fn) >= 2 and fn in lp:
        return True
    if ln and len(ln) >= 2 and ln in lp:
        return True
    # initial + last (jdoe) or first + initial (johnd)
    if fn and ln and (fn[0] + ln in lp or fn + ln[0] in lp):
        return True
    return False


def verify_company(domain: str) -> dict:
    """Parameter set answering: is the COMPANY behind this domain genuine?

    Returns a dict of named signals plus an overall ``genuine`` verdict and a
    ``reason`` when it is not genuine.
    """
    domain = (domain or "").lower()
    params = {
        "domain": domain,
        "is_free_or_disposable": domain in BLOCKED_DOMAINS,
        "has_mx": _has_mx_record(domain),
        "web_presence": _quick_web_check(domain),
        "website_reachable": _website_reachable(domain),
        "suspicious_tld": _suspicious_tld(domain),
    }

    # Decision: must not be free/disposable, must have mail (MX), and must be
    # corroborated on the web — either found in search, or (for a non-suspicious
    # TLD) serving a live site.
    reason = None
    if params["is_free_or_disposable"]:
        reason = "free/personal email domain"
    elif not params["has_mx"]:
        reason = "no MX record — not a valid business domain"
    elif not (params["web_presence"] or (params["website_reachable"] and not params["suspicious_tld"])):
        reason = "web lookup could not confirm this is a real company domain"

    params["genuine"] = reason is None
    params["reason"] = reason
    return params


def verify_user(local_part: str, first_name: str = "", last_name: str = "") -> dict:
    """Parameter set answering: is the USER a genuine individual, not anonymous?

    ``name_like`` and ``matches_lead_name`` are positive signals only — never
    used to reject (real employees are often not web-visible). A lead is rejected
    only on a positive fake signal: an auto-generated handle or a role mailbox.
    """
    params = {
        "local_part": local_part,
        "auto_generated": _looks_auto_generated(local_part),
        "role_account": _is_role_account(local_part),
        "name_like": _looks_like_name(local_part),
        "matches_lead_name": _matches_lead_name(local_part, first_name, last_name),
    }

    reason = None
    if params["auto_generated"]:
        reason = f"local-part '{local_part}' looks auto-generated/fake"
    elif params["role_account"]:
        reason = f"generic/role mailbox '{local_part}' — not an individual contact"

    params["genuine"] = reason is None
    params["reason"] = reason
    return params


def run(lead: Lead, db: Session) -> bool:
    """
    Gate 1: verify the lead by two independent parameter sets —
    (1) is the company/domain genuine, and (2) is the user a real individual.
    Rejects the lead if either check fails.
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

    # ── Check 2 (cheap, no network): is the USER a real individual? ──
    local_part = (lead.email or "").split("@")[0]
    user = verify_user(local_part, lead.first_name, lead.last_name)
    logger.info(
        "[gate:user] lead_id=%s email=%s params=%s",
        lead.id, lead.email, user,
    )
    if not user["genuine"]:
        logger.warning(
            "[gate:user] lead_id=%s email=%s — REJECTED (%s)",
            lead.id, lead.email, user["reason"],
        )
        lead.set_status(LeadStatus.INVALID_DOMAIN, db=db)
        return False

    # ── Check 1 (network): is the COMPANY/domain genuine? ───────────
    domain_lower = lead.domain.lower()
    company = verify_company(domain_lower)
    logger.info(
        "[gate:company] lead_id=%s domain=%s params=%s",
        lead.id, domain_lower, company,
    )
    if not company["genuine"]:
        logger.warning(
            "[gate:company] lead_id=%s domain=%s — REJECTED (%s)",
            lead.id, domain_lower, company["reason"],
        )
        lead.set_status(LeadStatus.INVALID_DOMAIN, db=db)
        return False

    logger.info(
        "[gate:domain] lead_id=%s domain=%s — PASSED (company + user verified)",
        lead.id, domain_lower,
    )
    return True
