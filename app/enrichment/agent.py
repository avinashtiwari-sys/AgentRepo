import json
import time
import anthropic
from config import ANTHROPIC_API_KEY

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a B2B talent intelligence agent. Given a company name and domain,
use web search to find QA/testing professionals employed there, and verify the company's
authenticity.

ROLE CRITERIA — only return profiles matching ALL of these:
- Seniority: Lead, Senior Lead, Test Manager, QA Manager, Senior Manager, Director of QA,
  VP Quality Engineering, Head of QA, Head of Testing, Head of Quality Engineering
- Domain: SOFTWARE testing only — mobile app testing, web automation, test engineering,
  SDET, performance testing, CI/CD quality, release engineering
- Must be a plausible hire for the given company based on its industry and size

CRITICAL — NEVER include profiles where QA/Quality refers to:
- Food safety, pharma compliance, manufacturing quality, construction, FMCG,
  or any non-software domain

You must return a JSON object with these fields:
{
  "employee_count": <integer or null>,
  "employee_range": "<string range e.g. '100-250' or null>",
  "industry": "<primary industry e.g. 'Banking', 'FinTech', 'SaaS'>",
  "web_presence": <true if company has a real website>,
  "is_competitor": <true if CRM/sales automation/GTM tool>,
  "confidence": "<high | med | low>",
  "sources": ["<url>"],
  "profiles": [
    {
      "name": "<full name>",
      "title": "<exact job title>",
      "seniority": "<Lead | Senior Lead | Test Manager | QA Manager | Senior Manager | Director of QA | VP Quality Engineering | Head of QA | Head of Testing | Head of Quality Engineering>",
      "linkedin": "<profile URL or null>",
      "summary": "<one-line bio highlighting software QA/testing expertise>",
      "match_reason": "<brief explanation of why this profile fits the criteria>"
    }
  ]
}

Confidence rules:
- high: employee count confirmed from 2+ sources (LinkedIn, Crunchbase, company site)
- med: employee count from 1 source or estimated from funding/revenue signals
- low: no reliable headcount data found, inference only

Return only the JSON object, no explanation."""

USER_PROMPT = """Research QA/testing leadership at this company:
Company name: {company}
Domain: {domain}

Search for:
1. "{company} QA director" or "{company} head of testing"
2. "{company} SDET manager" or "{company} quality engineering"
3. "{company} number of employees"
4. "{domain} company industry"

Focus on finding real LinkedIn profiles of QA/testing leaders at this company.
Only include profiles where QA/Quality is SOFTWARE testing — NOT food, pharma,
manufacturing, construction, or other non-software domains.

Return only the JSON object, no explanation."""


def run(company: str, domain: str) -> dict:
    for attempt in range(3):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": USER_PROMPT.format(company=company, domain=domain)}],
            )
            text = next((b.text.strip() for b in response.content if b.type == "text"), "")
            if text.startswith("```"):
                text = text.split("```")[1].removeprefix("json")
            return _validate(json.loads(text))
        except (anthropic.APIError, anthropic.RateLimitError) as e:
            if attempt < 2:
                time.sleep(2 * 2 ** attempt)
                continue
            return _fallback(str(e))
        except (json.JSONDecodeError, Exception) as e:
            return _fallback(str(e))


def _validate(d: dict) -> dict:
    valid_conf = d.get("confidence", "low") if d.get("confidence") in ("high", "med", "low") else "low"

    valid_seniorities = {
        "Lead", "Senior Lead", "Test Manager", "QA Manager", "Senior Manager",
        "Director of QA", "VP Quality Engineering", "Head of QA", "Head of Testing",
        "Head of Quality Engineering"
    }
    profiles = []
    for p in d.get("profiles", []):
        if not isinstance(p, dict):
            continue
        if p.get("seniority") not in valid_seniorities:
            continue
        profiles.append({
            "name": p.get("name", "Unknown"),
            "title": p.get("title", ""),
            "seniority": p.get("seniority", ""),
            "linkedin": p.get("linkedin"),
            "summary": p.get("summary", ""),
            "match_reason": p.get("match_reason", ""),
        })

    return {
        "employee_count": d.get("employee_count"),
        "employee_range": d.get("employee_range"),
        "industry": d.get("industry", "Unknown"),
        "web_presence": bool(d.get("web_presence", False)),
        "is_competitor": bool(d.get("is_competitor", False)),
        "confidence": valid_conf,
        "sources": d.get("sources", []),
        "profiles": profiles,
        "profile_count": len(profiles),
    }


def _fallback(reason: str) -> dict:
    return {
        "employee_count": None, "employee_range": None, "industry": "Unknown",
        "web_presence": False, "is_competitor": False, "confidence": "low",
        "sources": [], "profiles": [], "profile_count": 0, "error": reason,
    }
