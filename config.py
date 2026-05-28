from dotenv import load_dotenv
import os

load_dotenv()

ZOHO_WEBHOOK_SECRET = os.getenv("ZOHO_WEBHOOK_SECRET", "")
ZOHO_CLIENT_ID = os.getenv("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.getenv("ZOHO_CLIENT_SECRET", "")
ZOHO_REFRESH_TOKEN = os.getenv("ZOHO_REFRESH_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gtmflow.db")
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "")

REPS = {
    "smb": {"name": "Preksha", "email": os.getenv("REP_PREKSHA_EMAIL", "")},
    "enterprise": [
        {"name": "Srini", "email": os.getenv("REP_SRINI_EMAIL", "")},
        {"name": "Anuja", "email": os.getenv("REP_ANUJA_EMAIL", "")},
    ],
}

EMPLOYEE_THRESHOLD = 250
