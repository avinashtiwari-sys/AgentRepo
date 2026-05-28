import httpx
from config import TEAMS_WEBHOOK_URL


def send_lead_alert(lead_id: str, rep: dict, lead_info: dict):
    """Post an Adaptive Card to the Teams channel via incoming webhook."""
    if not TEAMS_WEBHOOK_URL:
        print("[teams] TEAMS_WEBHOOK_URL not set — skipping alert")
        return

    company = lead_info.get("company", "Unknown")
    email = lead_info.get("email", "")
    industry = lead_info.get("industry", "Unknown")
    employee_range = lead_info.get("employee_range") or str(lead_info.get("employee_count") or "Unknown")
    confidence = lead_info.get("confidence", "").upper()
    segment = lead_info.get("segment", "")

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": f"New MQL Assigned — {company}",
                            "weight": "Bolder",
                            "size": "Medium",
                            "color": "Accent",
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": "Assigned to", "value": rep["name"]},
                                {"title": "Segment",     "value": segment},
                                {"title": "Company",     "value": company},
                                {"title": "Email",       "value": email},
                                {"title": "Industry",    "value": industry},
                                {"title": "Employees",   "value": employee_range},
                                {"title": "Confidence",  "value": confidence},
                            ],
                        },
                    ],
                    "actions": [
                        {
                            "type": "Action.OpenUrl",
                            "title": "Open in Zoho CRM",
                            "url": f"https://crm.zoho.com/crm/org/leads/{lead_id}",
                        }
                    ],
                },
            }
        ],
    }

    try:
        resp = httpx.post(TEAMS_WEBHOOK_URL, json=card, timeout=10)
        if resp.status_code == 200:
            print(f"[teams] alert sent for lead {lead_id} → {rep['name']}")
        else:
            print(f"[teams] alert failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[teams] alert error: {e}")
