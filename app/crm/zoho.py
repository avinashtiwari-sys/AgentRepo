import httpx
from config import ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_REFRESH_TOKEN

TOKEN_URL = "https://accounts.zoho.com/oauth/v2/token"
CRM_BASE = "https://www.zohoapis.com/crm/v3"

_access_token_cache: dict = {"token": None}


def _get_access_token() -> str:
    """Exchange refresh token for a fresh access token."""
    resp = httpx.post(TOKEN_URL, params={
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    token = resp.json()["access_token"]
    _access_token_cache["token"] = token
    return token


def _headers() -> dict:
    token = _access_token_cache["token"] or _get_access_token()
    return {"Authorization": f"Zoho-oauthtoken {token}"}


def update_lead(lead_id: str, fields: dict) -> bool:
    """Write enriched fields back to the Zoho CRM lead record."""
    payload = {"data": [{**fields, "id": lead_id}]}

    resp = httpx.put(f"{CRM_BASE}/Leads", json=payload, headers=_headers())

    # Token expired — refresh once and retry
    if resp.status_code == 401:
        _access_token_cache["token"] = None
        resp = httpx.put(f"{CRM_BASE}/Leads", json=payload, headers=_headers())

    if resp.status_code not in (200, 201, 202):
        print(f"[zoho] update failed for lead {lead_id}: {resp.status_code} {resp.text}")
        return False

    print(f"[zoho] lead {lead_id} updated in CRM")
    return True


def mark_mql(lead_id: str, enrichment: dict, assigned_rep: str) -> bool:
    """Write MQL status and all enriched fields to Zoho."""
    fields = {
        "Lead_Status": "MQL - Valid",
        "Company_Size__c": enrichment.get("employee_range") or str(enrichment.get("employee_count") or ""),
        "Industry": enrichment.get("industry", ""),
        "Enrichment_Confidence__c": enrichment.get("confidence", ""),
        "Assigned_Rep__c": assigned_rep,
    }
    # Strip empty strings so we don't overwrite existing Zoho data with blanks
    fields = {k: v for k, v in fields.items() if v}
    return update_lead(lead_id, fields)
