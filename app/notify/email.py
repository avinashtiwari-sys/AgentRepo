import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM

ALERT_TO = "PcloudySalesMarketing@opkey.com"


def send_lead_alert(lead_id: str, rep: dict, lead_info: dict):
    """Send an HTML email alert via SMTP for a newly routed MQL."""
    if not SMTP_HOST or not SMTP_USER:
        print("[email] SMTP not configured — skipping alert")
        return

    company        = lead_info.get("company", "Unknown")
    lead_email     = lead_info.get("email", "")
    industry       = lead_info.get("industry", "Unknown")
    employee_range = lead_info.get("employee_range") or str(lead_info.get("employee_count") or "Unknown")
    confidence     = (lead_info.get("confidence") or "").upper()
    segment        = lead_info.get("segment", "")
    zoho_url       = f"https://crm.zoho.com/crm/org/leads/{lead_id}"

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
        <tr><td><b>Confidence</b></td><td>{confidence}</td></tr>
      </table>
      <br>
      <a href="{zoho_url}"
         style="background:#1a73e8;color:#fff;padding:10px 20px;
                text-decoration:none;border-radius:4px;display:inline-block">
        Open in Zoho CRM
      </a>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_FROM
    msg["To"]      = ALERT_TO
    msg.attach(MIMEText(html, "html"))

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, ALERT_TO, msg.as_string())
        print(f"[email] alert sent for lead {lead_id} → {ALERT_TO}")
    except Exception as e:
        print(f"[email] alert error: {e}")
