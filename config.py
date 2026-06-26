import os
from dotenv import load_dotenv

load_dotenv()

# -- Active provider ---------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()

# -- Provider registry -------------------------------------------------
# Each provider has its own API key and model env var.
# Add new providers here and in .env.
_PROVIDER_CONFIG = {
    "anthropic": {
        "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        "endpoint": "",  # uses Anthropic's default
    },
    "google": {
        "api_key": os.getenv("GOOGLE_API_KEY", ""),
        "model": os.getenv("GOOGLE_MODEL", "gemini-2.5-flash"),
        "endpoint": "",  # uses Google's default
    },
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "model": os.getenv("OPENAI_MODEL", "Qwen3-Coder-30B-A3B-Instruct"),
        "endpoint": os.getenv("OPENAI_ENDPOINT", "http://45.63.38.248:9000/v1/chat/completions"),
    },
}

# Resolve the active provider's config
_active = _PROVIDER_CONFIG.get(LLM_PROVIDER)
if _active is None:
    valid = ", ".join(_PROVIDER_CONFIG)
    raise RuntimeError(f"Unknown LLM_PROVIDER '{LLM_PROVIDER}'. Valid options: {valid}")

LLM_API_KEY = _active["api_key"]
LLM_MODEL = _active["model"]

# -- Resolve endpoint for OpenAI-compatible providers ------------------
LLM_ENDPOINT = _active.get("endpoint", "")

# -- Backward compat aliases -------------------------------------------
ANTHROPIC_API_KEY = _PROVIDER_CONFIG["anthropic"]["api_key"]
GOOGLE_API_KEY = _PROVIDER_CONFIG["google"]["api_key"]
OPENAI_API_KEY = _PROVIDER_CONFIG["openai"]["api_key"]

# -- Zoho CRM Webhook --------------------------------------------------
ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gtmflow.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# -- SMTP / Email ------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
ALERT_RECIPIENT_EMAIL = os.getenv("ALERT_RECIPIENT_EMAIL", "")
TEST_EMAIL = os.getenv("TEST_EMAIL", "")
MODE = os.getenv("MODE", "dev").lower()
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

# -- Web Search (Tavily) -----------------------------------------------
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


def validate_config():
    """Validate required config based on the active LLM provider."""
    if LLM_PROVIDER == "google":
        required = {"ZOHO_WEBHOOK_SECRET": ZOHO_WEBHOOK_SECRET, "GOOGLE_API_KEY": GOOGLE_API_KEY}
    elif LLM_PROVIDER == "openai":
        required = {"ZOHO_WEBHOOK_SECRET": ZOHO_WEBHOOK_SECRET, "OPENAI_API_KEY": OPENAI_API_KEY}
    else:
        required = {"ZOHO_WEBHOOK_SECRET": ZOHO_WEBHOOK_SECRET, "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY}
    missing = [n for n, v in required.items() if not v]
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing) + ". Set them in .env")
    optional_missing = [n for n in ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_RECIPIENT_EMAIL"] if not os.getenv(n)]
    if not TAVILY_API_KEY and LLM_PROVIDER == "openai":
        optional_missing.append("TAVILY_API_KEY (web search disabled for openai provider)")
    return optional_missing
