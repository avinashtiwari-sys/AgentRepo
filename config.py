from dotenv import load_dotenv
import os

load_dotenv()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET", "")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gtmflow.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "")
# No default — recipients are deployment-specific and must come from .env.
ALERT_RECIPIENT_EMAIL = os.getenv("ALERT_RECIPIENT_EMAIL", "")

# Vars that must be present for the service to function at all.
_REQUIRED = {
    "ZOHO_WEBHOOK_SECRET": ZOHO_WEBHOOK_SECRET,
    "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
}

# Vars the service can boot without, but that disable a feature when missing.
_RECOMMENDED = {
    "SMTP_HOST": SMTP_HOST,
    "SMTP_USER": SMTP_USER,
    "SMTP_PASSWORD": SMTP_PASSWORD,
    "ALERT_RECIPIENT_EMAIL": ALERT_RECIPIENT_EMAIL,
}


def validate_config():
    """Fail fast on missing required config; warn on missing optional config.

    Call once at startup (web + worker). Raises RuntimeError listing every
    missing required variable so misconfiguration surfaces at boot, not mid-job.
    """
    missing = [name for name, value in _REQUIRED.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Set them in .env (see .env.example)."
        )

    warnings = [name for name, value in _RECOMMENDED.items() if not value]
    return warnings
