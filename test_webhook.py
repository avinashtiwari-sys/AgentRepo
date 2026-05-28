"""
Local test — simulates a Zoho webhook POST.
Run with: python test_webhook.py

Make sure the server is running first:
  uvicorn app.main:app --reload
"""
import httpx

payload = {
    "leads": [
        {
            "id": "TEST-LEAD-001",
            "First_Name": "Jane",
            "Last_Name": "Smith",
            "Email": "jane@stripe.com",
            "Company": "Stripe",
            "Lead_Source": "Website",
        }
    ]
}

resp = httpx.post("http://localhost:8000/webhook/zoho", json=payload)
print(f"Status : {resp.status_code}")
print(f"Response: {resp.json()}")
