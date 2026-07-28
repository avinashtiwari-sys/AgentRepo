"""Balance and quota checks for paid external services.

Monitored services
------------------
1. **Tavily** — web search API (used by the OpenAI provider path).
   Checked via ``POST /account/usage``.

2. **Anthropic / Claude** — paid LLM provider.
   Checked via the billing balance endpoint. The org ID is resolved
   automatically on first call.

3. **Google Gemini** — paid LLM provider.
   Checked via the quota / usage endpoint (``generateContent`` with a
   minimal request to verify the key is valid and has quota).

4. **Local models (self-hosted Qwen / vLLM / Ollama)** — not checked.
   Self-hosted models have no usage limit, so their balance is always OK.

Usage
-----
    report = check_all_balances()
    send_balance_alerts(report)

Thresholds (env vars)
---------------------
- ``TAVILY_BALANCE_THRESHOLD`` — minimum remaining Tavily credits (default: 50)
- ``ANTHROPIC_BALANCE_THRESHOLD`` — minimum $ balance (default: 1.0)
- ``OPENAI_BALANCE_THRESHOLD`` — minimum $ balance (default: 1.0)
- ``GOOGLE_BALANCE_THRESHOLD`` — minimum $ balance / quota remaining (default: 1.0)
"""

import os
from typing import Optional, List
import httpx
from config import (
    LLM_PROVIDER,
    TAVILY_API_KEY,
    ANTHROPIC_API_KEY,
    GOOGLE_API_KEY,
    LLM_ENDPOINT,
)
from app.logging_config import logger

# ── Default thresholds (can be overridden via env) ────────────────────
# Tavily: alert when remaining credits drop below this number
TAVILY_THRESHOLD = int(os.getenv("TAVILY_BALANCE_THRESHOLD", "50"))
# LLM providers (Anthropic, OpenAI, Google): alert when remaining $ balance
# drops below this amount. Local/self-hosted models are skipped.
ANTHROPIC_THRESHOLD = float(os.getenv("ANTHROPIC_BALANCE_THRESHOLD", "1.0"))
GOOGLE_THRESHOLD = float(os.getenv("GOOGLE_BALANCE_THRESHOLD", "1.0"))
OPENAI_THRESHOLD = float(os.getenv("OPENAI_BALANCE_THRESHOLD", "1.0"))


# ── Tavily ────────────────────────────────────────────────────────────

def check_tavily_balance() -> dict:
    """Check remaining Tavily credits / quota.

    Strategy
    --------
    1. Try ``POST /account/usage`` (available on paid plans).
    2. If that returns 404 (dev/free plan), fall back to making a lightweight
       search call.  If the search returns HTTP 432 the daily quota is exhausted.

    Returns
    -------
    dict with keys:
        service: "tavily"
        status: "ok" | "low" | "error" | "skipped"
        remaining: int or None
        used: int or None
        total: int or None
        message: str
    """
    result = {"service": "tavily", "status": "ok", "remaining": None, "used": None, "total": None, "message": ""}

    if not TAVILY_API_KEY:
        result["status"] = "skipped"
        result["message"] = "TAVILY_API_KEY not set"
        return result

    # ── Step 1: try the dedicated usage endpoint ─────────────────────
    try:
        resp = httpx.post(
            "https://api.tavily.com/account/usage",
            json={"api_key": TAVILY_API_KEY},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            remaining = data.get("remaining_credits", data.get("remaining"))
            used = data.get("used_credit_count", data.get("used", 0))
            total = data.get("daily_credit_limit", data.get("total", data.get("max", 0)))

            result["remaining"] = remaining
            result["used"] = used
            result["total"] = total

            if remaining is not None and remaining < TAVILY_THRESHOLD:
                result["status"] = "low"
                result["message"] = (
                    f"Tavily credits running low — {remaining}/{total or '?'} remaining "
                    f"(threshold: {TAVILY_THRESHOLD})"
                )
            else:
                result["message"] = f"Tavily credits OK — {remaining}/{total or '?'} remaining"

            logger.info("[balance] tavily: %s", result["message"])
            return result

        # 404 → not available on this plan, fall through to step 2
        if resp.status_code != 404:
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            result["status"] = "error"
            result["message"] = f"HTTP {e.response.status_code}: {str(e)[:80]}"
            logger.error("[balance] tavily usage endpoint failed: %s", result["message"])
            return result
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)[:100]
        logger.error("[balance] tavily usage endpoint failed: %s", result["message"])
        return result

    # ── Step 2: fallback — probe with a search call ──────────────────
    # Dev plans don't expose the usage endpoint, so we detect exhaustion
    # by making a minimal search request (HTTP 432 = daily limit reached).
    try:
        probe = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": "ping",
                "max_results": 1,
                "search_depth": "basic",
            },
            timeout=15,
        )

        if probe.status_code == 432:
            result["status"] = "low"
            result["message"] = "Tavily daily search quota exhausted (HTTP 432)"
            logger.warning("[balance] tavily: %s", result["message"])
        elif probe.status_code == 200:
            result["status"] = "ok"
            result["message"] = "Tavily API key is valid and has quota remaining"
            logger.info("[balance] tavily: %s", result["message"])
        else:
            result["status"] = "error"
            result["message"] = f"Unexpected status {probe.status_code} on probe"
            logger.error("[balance] tavily probe: %s", result["message"])
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)[:100]
        logger.error("[balance] tavily probe failed: %s", result["message"])

    return result


# ── Anthropic ─────────────────────────────────────────────────────────

_anthropic_org_id = None


def _resolve_anthropic_org() -> Optional[str]:
    """Fetch the first organization ID from the Anthropic API.

    Returns the org ID string, or None on failure.
    """
    global _anthropic_org_id
    if _anthropic_org_id:
        return _anthropic_org_id

    try:
        resp = httpx.get(
            "https://api.anthropic.com/v1/organizations",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            timeout=15,
        )
        resp.raise_for_status()
        orgs = resp.json().get("data", [])
        if orgs:
            _anthropic_org_id = orgs[0]["id"]
            return _anthropic_org_id
        logger.warning("[balance] anthropic: no organizations found")
    except Exception as e:
        logger.warning("[balance] anthropic: could not resolve org: %s", str(e)[:80])
    return None


def check_anthropic_balance() -> dict:
    """Check remaining Anthropic billing balance.

    Returns
    -------
    dict with keys:
        service: "anthropic"
        status: "ok" | "low" | "error" | "skipped"
        balance: float or None
        message: str
    """
    result = {"service": "anthropic", "status": "ok", "balance": None, "message": ""}

    if not ANTHROPIC_API_KEY:
        result["status"] = "skipped"
        result["message"] = "ANTHROPIC_API_KEY not set"
        return result

    org_id = _resolve_anthropic_org()
    if not org_id:
        result["status"] = "error"
        result["message"] = "Could not resolve Anthropic organization ID"
        return result

    try:
        resp = httpx.get(
            f"https://api.anthropic.com/v1/organizations/{org_id}/billing/balance",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        balance = float(data.get("balance", 0))
        result["balance"] = balance

        if balance < ANTHROPIC_THRESHOLD:
            result["status"] = "low"
            result["message"] = (
                f"Anthropic balance low — ${balance:.2f} remaining "
                f"(threshold: ${ANTHROPIC_THRESHOLD:.2f})"
            )
        else:
            result["message"] = f"Anthropic balance OK — ${balance:.2f} remaining"

        logger.info("[balance] anthropic: %s", result["message"])

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            result["status"] = "skipped"
            result["message"] = "Anthropic billing endpoint not available for this plan"
            logger.warning("[balance] anthropic: %s", result["message"])
        else:
            result["status"] = "error"
            result["message"] = f"HTTP {e.response.status_code}: {str(e)[:80]}"
            logger.error("[balance] anthropic check failed: %s", result["message"])
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)[:100]
        logger.error("[balance] anthropic check failed: %s", result["message"])

    return result


# ── Google Gemini ─────────────────────────────────────────────────────

def check_google_balance() -> dict:
    """Check Google Gemini API key validity and remaining quota.

    Google doesn't expose a simple "balance" endpoint.  Instead we make
    a minimal generateContent call that costs nothing (1 token) and inspect
    the error / response to infer whether the key is active and has quota.

    Returns
    -------
    dict with keys:
        service: "google"
        status: "ok" | "low" | "error" | "skipped"
        message: str
    """
    result = {"service": "google", "status": "ok", "message": ""}

    if not GOOGLE_API_KEY:
        result["status"] = "skipped"
        result["message"] = "GOOGLE_API_KEY not set"
        return result

    from config import LLM_MODEL
    model = LLM_MODEL if LLM_PROVIDER == "google" else "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": "hi"}]}],
    }

    try:
        resp = httpx.post(
            url,
            headers={
                "Content-Type": "application/json",
                "X-goog-api-key": GOOGLE_API_KEY,
            },
            json=payload,
            timeout=15,
        )

        if resp.status_code == 429:
            result["status"] = "low"
            result["message"] = "Google Gemini quota exhausted (HTTP 429)"
        elif resp.status_code == 403:
            result["status"] = "low"
            result["message"] = "Google Gemini billing disabled or API key restricted (HTTP 403)"
        elif resp.status_code == 200:
            try:
                data = resp.json()
                prompt_feedback = data.get("promptFeedback", {})
                block_reason = prompt_feedback.get("blockReason")
                if block_reason:
                    result["status"] = "error"
                    result["message"] = f"Google Gemini blocked: {block_reason}"
                else:
                    result["message"] = "Google Gemini API key is valid and has quota"
            except Exception:
                result["message"] = "Google Gemini API key is valid"
        else:
            result["status"] = "error"
            result["message"] = f"HTTP {resp.status_code}: {str(resp.text)[:80]}"

        logger.info("[balance] google: %s", result["message"])

    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)[:100]
        logger.error("[balance] google check failed: %s", result["message"])

    return result


# ── Aggregator ────────────────────────────────────────────────────────

def check_all_balances() -> List[dict]:
    """Run balance checks for all applicable services.

    Skips checks for services that aren't configured or aren't relevant
    (e.g. local models).

    Returns
    -------
    list of result dicts (one per service).
    """
    results = []

    # Always check Tavily (used by every provider)
    results.append(check_tavily_balance())

    # Check LLM provider balance only if it's a paid provider
    if LLM_PROVIDER == "anthropic":
        results.append(check_anthropic_balance())
    elif LLM_PROVIDER == "google":
        results.append(check_google_balance())
    elif LLM_PROVIDER == "openai":
        # The OpenAI-compatible endpoint may point to a local model or to
        # the real OpenAI API.  We detect "local" by checking a few common
        # patterns: private IP, 127.0.0.1, or non-openai.com hosts.
        _endpoint = (LLM_ENDPOINT or "").lower()
        _is_local = any(
            pattern in _endpoint
            for pattern in [
                "localhost", "127.0.0.1", "192.168.", "10.",
                "172.16.", "172.17.", "172.18.", "172.19.",
                "172.20.", "172.21.", "172.22.", "172.23.",
                "172.24.", "172.25.", "172.26.", "172.27.",
                "172.28.", "172.29.", "172.30.", "172.31.",
            ]
        ) or (
            # Also detect non-OpenAI FQDNs — these are self-hosted models.
            "api.openai.com" not in _endpoint
            and "api.openai.com" not in _endpoint
        )

        if _is_local:
            results.append({
                "service": "openai",
                "status": "ok",
                "message": "Local/self-hosted model — no balance to check",
            })
            logger.info("[balance] openai: local/self-hosted model — skipping balance check")
        else:
            # Pointed at real OpenAI — try credits endpoint
            results.append(check_openai_balance())

    return results


def check_openai_balance() -> dict:
    """Check OpenAI account billing balance / credits.

    Uses the OpenAI dashboard billing API.

    Returns
    -------
    dict with keys:
        service: "openai"
        status: "ok" | "low" | "error" | "skipped"
        balance: float or None
        message: str
    """
    result = {"service": "openai", "status": "ok", "balance": None, "message": ""}

    from config import OPENAI_API_KEY
    if not OPENAI_API_KEY:
        result["status"] = "skipped"
        result["message"] = "OPENAI_API_KEY not set"
        return result

    try:
        # OpenAI billing credit grants endpoint
        resp = httpx.get(
            "https://api.openai.com/v1/dashboard/billing/credit_grants",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        total_granted = data.get("total_granted", 0)
        total_used = data.get("total_used", 0)
        total_available = data.get("total_available", 0)
        balance = float(total_available)

        result["balance"] = balance
        threshold = OPENAI_THRESHOLD

        if balance < threshold:
            result["status"] = "low"
            result["message"] = (
                f"OpenAI balance low — ${balance:.2f} available "
                f"(threshold: ${threshold:.2f})"
            )
        else:
            result["message"] = (
                f"OpenAI balance OK — ${balance:.2f} available "
                f"(${total_used:.2f} used of ${total_granted:.2f} granted)"
            )

        logger.info("[balance] openai: %s", result["message"])

    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403, 404):
            result["status"] = "skipped"
            result["message"] = f"OpenAI billing endpoint not accessible: HTTP {e.response.status_code}"
            logger.warning("[balance] openai: %s", result["message"])
        else:
            result["status"] = "error"
            result["message"] = f"HTTP {e.response.status_code}: {str(e)[:80]}"
            logger.error("[balance] openai check failed: %s", result["message"])
    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)[:100]
        logger.error("[balance] openai check failed: %s", result["message"])

    return result


# ── Alerting ──────────────────────────────────────────────────────────

def has_low_balances(results: List[dict]) -> List[dict]:
    """Filter a list of balance results to only those with a low status."""
    return [r for r in results if r.get("status") == "low"]


def format_balance_report(results: List[dict]) -> str:
    """Build a human-readable plain-text summary of balance checks."""
    lines = ["GTMFlow — Balance & Quota Report", "=" * 40]

    for r in results:
        status_tag = {
            "ok": "✓",
            "low": "⚠ LOW",
            "error": "✗ ERROR",
            "skipped": "— skipped",
        }.get(r.get("status", ""), "?")

        service = r["service"]
        msg = r.get("message", "No details")

        if r.get("remaining") is not None:
            details = f" (remaining: {r['remaining']})"
        elif r.get("balance") is not None:
            details = f" (balance: ${r['balance']:.2f})"
        else:
            details = ""

        lines.append(f"  [{status_tag:>8}] {service}{details}")
        lines.append(f"           {msg}")

    return "\n".join(lines)
