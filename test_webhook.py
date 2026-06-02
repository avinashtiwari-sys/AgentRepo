"""
Local test — simulates a Zoho Contacts webhook POST.
Run with: python test_webhook.py

Make sure the server is running first:
  uvicorn app.main:app --reload
"""
import httpx
from config import ZOHO_WEBHOOK_SECRET

payload = {
    "token": ZOHO_WEBHOOK_SECRET or "pcloudy_secure_2026",
    "contact_id": "TEST-CONTACT-002",
    "contact_name": "Jane Smith",
    "email": "jane@stripe.com",
    "company": "Stripe",
    "lead_source": "Website",
}

print(f"Testing with token: {ZOHO_WEBHOOK_SECRET[:4]}***")
resp = httpx.post(
    "http://localhost:8000/webhook/zoho",
    json=payload,
)
print(f"Status : {resp.status_code}")
print(f"Response: {resp.json()}")
