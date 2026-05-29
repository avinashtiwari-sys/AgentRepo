"""
Local test — simulates a Zoho Contacts webhook POST.
Run with: python test_webhook.py

Make sure the server is running first:
  uvicorn app.main:app --reload
"""
import httpx

payload = {
    "contact_id": "TEST-CONTACT-001",
    "contact_name": "Jane Smith",
    "email": "jane@stripe.com",
    "company": "Stripe",
    "lead_source": "Website",
    "phone": "9876543210",
    "mobile": "9876543210",
}

resp = httpx.post(
    "http://localhost:8000/webhook/zoho",
    params={"X-Zoho-Webhook-Token": "pcloudy_secure_2026"},
    json=payload,
)
print(f"Status : {resp.status_code}")
print(f"Response: {resp.json()}")
