import json
import time
import httpx
import anthropic
from config import LLM_PROVIDER, LLM_API_KEY, LLM_MODEL
from app.logging_config import logger

# ── Provider setup ────────────────────────────────────────────────────
# LLM_PROVIDER selects the provider. LLM_MODEL and LLM_API_KEY are
# resolved automatically from the provider registry in config.py.

if LLM_PROVIDER == "google":
    logger.info("[enrichment] using provider=google model=%s", LLM_MODEL)
else:
    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    logger.info("[enrichment] using provider=anthropic model=%s", LLM_MODEL) 

MODEL = LLM_MODEL

SYSTEM_PROMPT = """You are a B2B sales intelligence agent. Given a company domain and a lead contact person, find company info and the person's LinkedIn profile.

You must return a JSON object with exactly these fields:
{
  "employee_count": <integer or null>,
  "employee_range": "<string or null>",
  "industry": "<string>",
  "web_presence": <true/false>,
  "is_competitor": <true/false>,
  "confidence": "high" | "med" | "low",
  "sources": ["<url>"],
  "profiles": [
    {
      "name": "<string>",
      "title": "<string — set to "Unknown" if not found>",
      "seniority": "<string — set to "Unknown" if not found>",
      "summary": "<string — set to "Unknown" if not found>",
      "linkedin": "<full LinkedIn profile URL if found, or "Unknown">"
    }
  ]
}

IMPORTANT — how to find the person:
Step 1: Search the domain broadly to discover the company and its employees (e.g. search "{domain}" employees LinkedIn).
Step 2: From the search results, identify the specific person: {contact_name}. Look for their name appearing alongside the company.
Step 3: If found, include their LinkedIn URL and job title. If not found, set to "Unknown".

CRITICAL: The "profiles" array must contain ONLY {contact_name} — no executives, no founders, no other employees. But you may search broadly in step 1 to discover them.

Confidence rules:
- high: employee count confirmed from 2+ sources
- med: employee count from 1 source
- low: no reliable headcount data
"""

USER_PROMPT = """Research this lead:
Domain: {domain}
Contact: {contact_name} ({email})

1. Search: "{domain}" site:linkedin.com/in employees people — find who works there
2. Search: "{domain}" company information number of employees industry
3. From the results, find {contact_name} and include ONLY them in profiles.

Return the JSON only. No explanation."""


def run(company: str, domain: str, contact_name: str = "", email: str = "") -> dict:
    """Call LLM with web search to extract company size, industry, and confidence."""
    max_retries = 3
    retry_delay = 2

    prompt = USER_PROMPT.format(company=company, domain=domain, contact_name=contact_name or company, email=email or "")

    for attempt in range(max_retries):
        try:
            if LLM_PROVIDER == "google":
                result_text, metadata = _call_gemini(prompt)
            else:
                result_text, metadata = _call_anthropic(prompt)

            data = json.loads(result_text)
            result = _validate(data)

            # Inject search metadata into the result
            if metadata.get("search_queries"):
                result["_search_queries"] = metadata["search_queries"]
            if metadata.get("sources"):
                web_sources = [s["uri"] for s in metadata["sources"] if s.get("uri")]
                # Merge grounding sources into the sources array (avoid dupes)
                existing = set(result.get("sources", []))
                for url in web_sources:
                    if url not in existing:
                        result.setdefault("sources", []).append(url)
                        existing.add(url)

            return result

        except (anthropic.APIError, anthropic.RateLimitError) as e:
            retryable = True
            err_msg = f"Anthropic API: {str(e)[:100]}"
        except json.JSONDecodeError:
            logger.error("[enrichment] company=%s domain=%s — could not parse LLM response", company, domain)
            return _fallback("could not parse LLM response")
        except Exception as e:
            # Covers Gemini errors and anything else
            retryable = not _is_fatal(e)
            err_msg = str(e)[:100]

        if retryable and attempt < max_retries - 1:
            wait = retry_delay * (2 ** attempt)
            logger.warning(
                "[enrichment] company=%s domain=%s — retryable error, retrying in %ss (attempt %s/%s): %s",
                company, domain, wait, attempt + 1, max_retries, err_msg,
            )
            time.sleep(wait)
            continue
        return _fallback(f"{err_msg}")


def _call_anthropic(prompt: str) -> tuple:
    """Call Claude with web search tool, return (json_text, metadata_dict)."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": prompt}],
    )
    result_text = ""
    for block in response.content:
        if block.type == "text":
            result_text += block.text + "\n"
    return _extract_json(result_text), {"search_queries": [], "sources": []}


def _call_gemini(prompt: str) -> tuple:
    """Call Gemini with Google Search grounding via REST API, return (json_text, metadata_dict)."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}],
    }
    resp = httpx.post(
        url,
        headers={"Content-Type": "application/json", "X-goog-api-key": LLM_API_KEY},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    candidate = data.get("candidates", [{}])[0]
    text = candidate.get("content", {}).get("parts", [{}])[0].get("text", "")

    # Extract search metadata that Gemini normally hides
    gm = candidate.get("groundingMetadata", {})
    search_queries = gm.get("webSearchQueries", [])
    grounding_sources = []
    for chunk in gm.get("groundingChunks", []):
        w = chunk.get("web", {})
        if w.get("uri"):
            grounding_sources.append({"title": w.get("title", ""), "uri": w["uri"]})

    metadata = {
        "search_queries": search_queries,
        "sources": grounding_sources,
    }

    # Log what was searched so user can see it
    if search_queries:
        logger.info("[enrichment:search] queries=%s", search_queries)
    if grounding_sources:
        logger.info("[enrichment:search] sources=%d — %s", len(grounding_sources),
                     [s["uri"] for s in grounding_sources[:5]])

    return _extract_json(text), metadata


def _extract_json(text: str) -> str:
    """Extract JSON object from LLM response — handles fences and preamble."""
    import re

    # Strategy 1: look for ```json ... ``` or ``` ... ``` code fence
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    # Strategy 2: find the first { and match braces
    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    text = text[brace_start:i + 1]
                    break

    return text.strip()


def _is_fatal(e: Exception) -> bool:
    """Check if an error is non-retryable."""
    msg = str(e).lower()
    if "invalid" in msg and ("api" in msg or "key" in msg or "auth" in msg):
        return True
    if "not found" in msg or "not supported" in msg:
        return True
    if "permission" in msg and "denied" in msg:
        return True
    return False


def _validate(data: dict) -> dict:
    """Ensure all required keys are present with safe defaults."""
    return {
        "employee_count": data.get("employee_count"),
        "employee_range": data.get("employee_range"),
        "industry": data.get("industry", "Unknown"),
        "web_presence": bool(data.get("web_presence", False)),
        "is_competitor": bool(data.get("is_competitor", False)),
        "confidence": data.get("confidence", "low") if data.get("confidence") in ("high", "med", "low") else "low",
        "sources": data.get("sources", []),
        "profiles": data.get("profiles", []),
    }


def _fallback(reason: str) -> dict:
    return {
        "employee_count": None,
        "employee_range": None,
        "industry": "Unknown",
        "web_presence": False,
        "is_competitor": False,
        "confidence": "low",
        "sources": [],
        "profiles": [],
        "error": reason,
    }
