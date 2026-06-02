import smtplib
import ssl
from datetime import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, ALERT_RECIPIENT_EMAIL

def send_lead_alert(lead_id: str, rep: dict, lead_info: dict):
    """Send an HTML email alert via SMTP for a newly routed MQL."""
    if not SMTP_HOST or not SMTP_USER:
        print("[email] SMTP not configured — skipping alert")
        return

    company        = lead_info.get("company", "Unknown")
    lead_email     = lead_info.get("email", "")
    industry       = lead_info.get("industry", "Unknown")
    employee_range = lead_info.get("employee_range") or str(lead_info.get("employee_count") or "Unknown")
    confidence     = (lead_info.get("confidence") or "low").lower()
    sources        = lead_info.get("sources", [])
    segment        = lead_info.get("segment", "")
    zoho_url       = f"https://crm.zoho.com/crm/org/leads/{lead_id}"

    # Accuracy Styling
    accuracy_colors = {"high": "#28a745", "med": "#ffc107", "low": "#dc3545"}
    accuracy_color = accuracy_colors.get(confidence, "#dc3545")
    accuracy_label = {
        "high": "High Accuracy (Verified)",
        "med": "Moderate Accuracy (Estimated)",
        "low": "Low Accuracy (Inferred)"
    }.get(confidence, "Low Accuracy")

    sources_html = ""
    if sources:
        links = [f'<a href="{s}">{s[:30]}...</a>' for s in sources[:3]]
        sources_html = f"<tr><td><b>Verification Sources</b></td><td>{', '.join(links)}</td></tr>"

    received_at = lead_info.get("received_at")
    # ... (timestamp logic)
    if received_at:
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        timestamp = received_at.strftime("%d %b %Y, %I:%M %p UTC")
    else:
        timestamp = "N/A"

    subject = f"New MQL: {company} → {rep['name']}"

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#222;max-width:600px">
      <h2 style="color:#1a73e8">New MQL Assigned — {company}</h2>
      <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
        <tr><td><b>Assigned Rep</b></td><td>{rep['name']}</td></tr>
        <tr style="background:#f5f5f5"><td><b>Segment</b></td><td>{segment}</td></tr>
        <tr><td><b>Company</b></td><td>{company}</td></tr>
        <tr style="background:#f5f5f5"><td><b>Lead Email</b></td><td>{lead_email}</td></tr>
        <tr><td><b>Industry</b></td><td>{industry}</td></tr>
        <tr style="background:#f5f5f5"><td><b>Employees</b></td><td>{employee_range}</td></tr>
        <tr>
          <td><b>Data Accuracy Profile</b></td>
          <td><span style="color:{accuracy_color};font-weight:bold">{accuracy_label}</span></td>
        </tr>
        {sources_html}
        <tr style="background:#f5f5f5"><td><b>Received At</b></td><td>{timestamp}</td></tr>
      </table>
      <br>
      <a href="{zoho_url}"
         style="background:#1a73e8;color:#fff;padding:10px 20px;
                text-decoration:none;border-radius:4px;display:inline-block">
        Open in Zoho CRM
      </a>
      <p style="font-size:12px;color:#666;margin-top:20px">
        Note: Accuracy is determined via real-time web search enrichment (Claude AI).
      </p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = ALERT_RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, ALERT_RECIPIENT_EMAIL, msg.as_string())
        print(f"[email] alert sent for lead {lead_id} → {ALERT_RECIPIENT_EMAIL}")
    except Exception as e:
        print(f"[email] alert error: {e}")
