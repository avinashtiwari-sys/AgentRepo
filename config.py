import os
from dotenv import load_dotenv

load_dotenv()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gtmflow.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
ALERT_RECIPIENT_EMAIL = os.getenv("ALERT_RECIPIENT_EMAIL", "")
TEST_EMAIL = os.getenv("TEST_EMAIL", "")
MODE = os.getenv("MODE", "dev").lower()
SENTRY_DSN = os.getenv("SENTRY_DSN", "")

_REQUIRED = {"ZOHO_WEBHOOK_SECRET": ZOHO_WEBHOOK_SECRET, "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY}


def validate_config():
    missing = [n for n, v in _REQUIRED.items() if not v]
    if missing:
        raise RuntimeError("Missing required env vars: " + ", ".join(missing) + ". Set them in .env")
    return [n for n in ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "ALERT_RECIPIENT_EMAIL"] if not os.getenv(n)]
