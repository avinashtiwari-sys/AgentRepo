import json
import time
import anthropic
from config import ANTHROPIC_API_KEY
from app.logging_config import logger

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """You are a B2B sales intelligence agent. Given a company name and domain,
use web search to find accurate information about the company, including finding key employee profiles (especially QA or Testing roles if possible) from LinkedIn or other sources.

You must return a JSON object with exactly these fields:
{
  "employee_count": <integer or null if unknown>,
  "employee_range": "<string range e.g. '100-250' or null>",
  "industry": "<primary industry e.g. 'SaaS', 'FinTech', 'Healthcare IT'>",
  "web_presence": <true if company has a real website and online presence>,
  "is_competitor": <true if the company is a CRM, sales automation, or GTM tool>,
  "confidence": "<high | med | low>",
  "sources": ["<url>"],
  "profiles": [
    {
      "name": "<string>",
      "title": "<string>",
      "seniority": "<string, e.g. Manager, Director, IC>",
      "summary": "<string, brief expertise summary>",
      "linkedin": "<string, LinkedIn URL or empty string>"
    }
  ]
}

Confidence rules:
- high: employee count confirmed from 2+ sources (LinkedIn, Crunchbase, company site)
- med: employee count from 1 source or estimated from funding/revenue signals
- low: no reliable headcount data found, inference only
"""

USER_PROMPT = """Research this company:
Company name: {company}
Domain: {domain}

Search for:
1. "{company} number of employees"
2. "{domain} company industry"
3. "{company} QA OR Testing OR Engineering LinkedIn"

Return only the JSON object, no explanation."""


def run(company: str, domain: str) -> dict:
    """Call Claude with web search to extract company size, industry, and confidence."""
    max_retries = 3
    retry_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[
                    {
                        "role": "user",
                        "content": USER_PROMPT.format(company=company, domain=domain),
                    }
                ],
            )

            # Extract the final text block from the response
            result_text = ""
            for block in response.content:
                if block.type == "text":
                    result_text = block.text.strip()

            # Parse JSON — strip markdown fences if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            data = json.loads(result_text)
            return _validate(data)

        except (anthropic.APIError, anthropic.RateLimitError) as e:
            if attempt < max_retries - 1:
                wait = retry_delay * (2 ** attempt)
                logger.warning(
                    "[enrichment] company=%s domain=%s — API error, retrying in %ss (attempt %s/%s)",
                    company, domain, wait, attempt + 1, max_retries
                )
                time.sleep(wait)
                continue
            return _fallback(f"Claude API failed after {max_retries} attempts: {str(e)}")
        except json.JSONDecodeError:
            logger.error("[enrichment] company=%s domain=%s — could not parse Claude response", company, domain)
            return _fallback("could not parse Claude response")
        except Exception as e:
            logger.exception("[enrichment] company=%s domain=%s — unexpected error", company, domain)
            return _fallback(str(e))


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
