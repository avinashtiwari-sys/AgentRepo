import json
import time
import httpx
import anthropic
from config import LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, LLM_ENDPOINT, TAVILY_API_KEY
from app.logging_config import logger
from app.enrichment.company_cache import COMPANY_FIELDS

# ── Provider setup ────────────────────────────────────────────────────
# LLM_PROVIDER selects the provider. LLM_MODEL and LLM_API_KEY are
# resolved automatically from the provider registry in config.py.

if LLM_PROVIDER == "google":
    logger.info("[enrichment] using provider=google model=%s", LLM_MODEL)
elif LLM_PROVIDER == "openai":
    logger.info("[enrichment] using provider=openai model=%s endpoint=%s", LLM_MODEL, LLM_ENDPOINT)
else:
    client = anthropic.Anthropic(api_key=LLM_API_KEY)
    logger.info("[enrichment] using provider=anthropic model=%s", LLM_MODEL) 

MODEL = LLM_MODEL

SYSTEM_PROMPT = """You are a B2B sales intelligence agent. Given a company domain and a lead contact person, find company info and the person's LinkedIn profile.

You must return a JSON object with exactly these fields:
{
  "company_name": "<string — the company name derived from the domain. REQUIRED. Do NOT leave empty.>",
  "employee_count": <integer or null>,
  "employee_range": "<string or null>",
  "industry": "<string>",
  "web_presence": <true/false>,
  "is_competitor": <true/false>,
  "is_spam": <true/false>,
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

Person search — look across ALL these sources (not just LinkedIn):
- LinkedIn (linkedin.com/in/)
- Twitter/X (twitter.com/, x.com/)
- GitHub (github.com/)
- Crunchbase (crunchbase.com/person/)
- AngelList / Wellfound (wellfound.com/)
- ZoomInfo, Apollo, Lusha
- Company "Team" or "About" pages
- Any professional profile or directory listing

If found on any platform, include that URL. If truly not found anywhere, set to "Unknown".

Confidence rules:
- high: employee count confirmed from 2+ sources
- med: employee count from 1 source
- low: no reliable headcount data

Spam / fake-contact rules — flag ONLY on positive evidence of fakeness:
- Set "is_spam": true ONLY when you have a concrete signal that the contact or domain is fake:
  * The email local-part (before the @) is clearly auto-generated, random, or junk — e.g.
    "asdf", "fbn990", "duskstag783", keyboard mashing, or random letter/number strings.
  * The company domain itself is a spam, disposable, parked, or obviously made-up domain.
  * Your search results affirmatively contradict the contact — e.g. the name belongs to a
    completely different, unrelated entity, or the domain resolves to a scam/parked page.
- DO NOT set "is_spam": true merely because you could not find the person. Most real employees
  do not appear in a quick web search. Absence of evidence is NOT evidence of fakeness.
- When unsure, leave "is_spam": false and reflect your uncertainty in "confidence" instead.
- "web_presence" describes the COMPANY, not the contact — set it true if the company is real.
"""

USER_PROMPT = """Research this lead:
Domain: {domain}
Contact: {contact_name} ({email})

1. Determine the company name from the domain — if the domain is "intecbusiness.co.uk", the company is likely "inTEC Business" or similar.
2. Search for the domain and company info: "{domain}" company information number of employees industry
3. Search for the person across ALL platforms:
   - "{contact_name}" "{domain}" linkedin
   - "{contact_name}" "{domain}" twitter
   - "{contact_name}" "{domain}" github
   - "{contact_name}" "{domain}" crunchbase
4. Set "company_name" to the actual company name you discovered (never leave it empty — use the domain to infer if needed).
5. In the "profiles" array, include {contact_name} with their title and profile URL from whichever platform you found them on (LinkedIn, Twitter, GitHub, etc.). If truly not found anywhere, set to "Unknown".

Return the JSON only. No explanation."""


def run(company: str, domain: str, contact_name: str = "", email: str = "", company_context: dict = None) -> dict:
    """Call LLM with web search to extract company size, industry, and confidence.

    When ``company_context`` is provided (a cached company-level enrichment for
    this domain), the company-level fields are reused as authoritative and the
    redundant company web searches are skipped — only the per-person lookup runs.
    """
    max_retries = 3
    retry_delay = 2

    prompt = USER_PROMPT.format(company=company, domain=domain, contact_name=contact_name or company, email=email or "")

    for attempt in range(max_retries):
        try:
            if LLM_PROVIDER == "google":
                result_text, metadata = _call_gemini(prompt)
            elif LLM_PROVIDER == "openai":
                result_text, metadata = _call_openai(prompt, domain, contact_name, email, company_context=company_context)
            else:
                result_text, metadata = _call_anthropic(prompt)

            data = json.loads(result_text)
            result = _validate(data)

            # Reuse cached company facts as authoritative (person fields stay fresh).
            if company_context:
                for k in COMPANY_FIELDS:
                    val = company_context.get(k)
                    if val is not None:
                        result[k] = val

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
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            retryable = status in (429, 500, 502, 503)
            err_msg = f"HTTP {status}: {str(e)[:100]}"
        except httpx.TimeoutException as e:
            retryable = True
            err_msg = f"Timeout: {str(e)[:100]}"
        except httpx.ConnectError as e:
            retryable = True
            err_msg = f"Connection refused: {str(e)[:100]}"
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


def _search_tavily(query: str, max_results: int = 5) -> list:
    """Search the web via Tavily API and return a list of result dicts."""
    if not TAVILY_API_KEY:
        logger.warning("[tavily] TAVILY_API_KEY not set — skipping web search")
        return []
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "advanced",
                "max_results": max_results,
                "include_answer": False,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        logger.info("[tavily] query=%s — %d results", query, len(results))
        return results
    except Exception as e:
        logger.warning("[tavily] query=%s — search failed: %s", query, str(e)[:100])
        return []


def _call_openai(prompt: str, domain: str = "", contact_name: str = "", email: str = "", company_context: dict = None) -> tuple:
    """Call an OpenAI-compatible endpoint (local LLM). Returns (json_text, metadata_dict).

    Because local models don't have built-in web search, we first gather
    context via Tavily, then feed it into the LLM prompt. When company facts are
    already cached (``company_context``), the company-level searches are skipped
    and only the per-person searches run.
    """
    # 1. Gather search context via Tavily
    search_domain = domain.strip() if domain else MODEL
    # Skip the company searches on a cache hit — we already have the company facts.
    if company_context:
        search_queries = []
    else:
        search_queries = [
            f"{search_domain} company information number of employees industry",
            f"{search_domain} employees LinkedIn",
        ]
    # Add person searches across multiple platforms
    person_name = contact_name.strip() if contact_name else ""
    if person_name:
        search_queries.extend([
            f'"{person_name}" "{search_domain}" linkedin',
            f'"{person_name}" "{search_domain}" twitter',
            f'"{person_name}" "{search_domain}" github',
        ])
    
    # Also search for the email username (the client/user part) to verify authenticity
    email_username = email.split("@")[0].strip() if email and "@" in email else ""
    if email_username and email_username.lower() not in ["info", "sales", "contact", "support", "admin", "hello"]:
        search_queries.append(f'"{email_username}" "{search_domain}" employee OR profile')
        
    all_sources = []
    for q in search_queries:
        results = _search_tavily(q, max_results=4)
        all_sources.extend(results)

    # 2. Build an enriched prompt with the search results
    search_context = ""
    uris = []
    for i, r in enumerate(all_sources[:12], 1):
        title = r.get("title", "")
        snippet = r.get("content", "") or r.get("snippet", "")
        url = r.get("url", "")
        if url:
            uris.append(url)
        search_context += f"\n[{i}] {title}\n    URL: {url}\n    {snippet}\n"

    enriched_prompt = f"""{prompt}

--- WEB SEARCH RESULTS ---
{search_context or "No search results found."}
--- END SEARCH RESULTS ---

Based on the search results above, return the JSON only. No explanation."""

    # 3. Call the OpenAI-compatible endpoint
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": enriched_prompt},
        ],
        "max_tokens": 2048,
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }

    resp = httpx.post(LLM_ENDPOINT, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    # 4. Extract text from OpenAI-style response
    choices = data.get("choices", [])
    text = choices[0].get("message", {}).get("content", "") if choices else ""

    metadata = {
        "search_queries": search_queries,
        "sources": [{"uri": u} for u in uris],
    }

    if search_queries:
        logger.info("[enrichment:search] queries=%s", search_queries)
    if uris:
        logger.info("[enrichment:search] sources=%d — %s", len(uris), uris[:5])

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
        "company_name": (data.get("company_name") or "").strip(),
        "employee_count": data.get("employee_count"),
        "employee_range": data.get("employee_range"),
        "industry": data.get("industry", "Unknown"),
        "web_presence": bool(data.get("web_presence", False)),
        "is_competitor": bool(data.get("is_competitor", False)),
        "is_spam": bool(data.get("is_spam", False)),
        "confidence": data.get("confidence", "low") if data.get("confidence") in ("high", "med", "low") else "low",
        "sources": data.get("sources", []),
        "profiles": data.get("profiles", []),
    }


def _fallback(reason: str) -> dict:
    return {
        "company_name": "",
        "employee_count": None,
        "employee_range": None,
        "industry": "Unknown",
        "web_presence": False,
        "is_competitor": False,
        "is_spam": False,
        "confidence": "low",
        "sources": [],
        "profiles": [],
        "error": reason,
    }
