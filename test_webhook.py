"""
Local test — simulates a Zoho webhook POST with real field names.
Run with: python test_webhook.py

Make sure the server is running first:
  uvicorn app.main:app --reload
"""
import httpx

payload = {
    "lead_id": "TEST-LEAD-001",
    "first_name": "Jane",
    "last_name": "Smith",
    "email": "jane@stripe.com",
    "company": "Stripe",
    "phone": "9876543210",
}

# Token sent as query param — matches Zoho's Custom Parameters behaviour
resp = httpx.post(
    "http://localhost:8000/webhook/zoho",
    params={"X-Zoho-Webhook-Token": "pcloudy_secure_2026"},
    json=payload,
)
print(f"Status : {resp.status_code}")
print(f"Response: {resp.json()}")
