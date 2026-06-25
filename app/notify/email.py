import smtplib
import ssl
from datetime import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, ALERT_RECIPIENT_EMAIL, TEST_EMAIL, MODE
from app.logging_config import logger

def send_lead_alert(lead_id: str, rep: dict, lead_info: dict):
    if not SMTP_HOST or not SMTP_USER:
        logger.warning("[email] SMTP not configured — skipping alert")
        return

    company = lead_info.get("company", "Unknown") or "Unknown"
    emp_count = lead_info.get("employee_count")
    emp_range = lead_info.get("employee_range") or (str(emp_count) if emp_count else "Unknown")
    confidence = (lead_info.get("confidence") or "low").lower()
    sources = lead_info.get("sources", [])[:3]
    zoho_url = f"https://crm.zoho.com/crm/org/leads/{lead_id}"

    styles = {"high": ("#28a745", "High Accuracy"), "med": ("#ffc107", "Moderate Accuracy"), "low": ("#dc3545", "Low Accuracy")}
    acc_color, acc_label = styles.get(confidence, ("#dc3545", "Low Accuracy"))

    ts = lead_info.get("received_at")
    if ts:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        timestamp = ts.strftime("%d %b %Y, %I:%M %p UTC")
    else:
        timestamp = "N/A"

    sources_row = ""
    if sources:
        links = "".join(f'<li><a href="{s}">{s[:35]}...</a></li>' for s in sources)
        sources_row = f"<tr><td><b>Sources</b></td><td><ul style=padding-left:16px;margin:0>{links}</ul></td></tr>"

    profiles = lead_info.get("profiles", [])
    profiles_section = ""
    if profiles:
        rows = ""
        for i, p in enumerate(profiles[:10], 1):
            linkedin = p.get("linkedin", "")
            name = p.get("name", "Unknown")
            title = p.get("title", "")
            seniority = p.get("seniority", "")
            summary = p.get("summary", "")
            linkedin_html = f'<a href="{linkedin}" style=color:#1a73e8>LinkedIn</a>' if linkedin else "N/A"
            bg = "#f9f9f9" if i % 2 == 0 else "#ffffff"
            rows += f"""<tr style=background:{bg}>
<td style=padding:8px;border-bottom:1px solid #ddd><b>{name}</b><br><span style=font-size:12px;color:#666>{title}</span></td>
<td style=padding:8px;border-bottom:1px solid #ddd;font-size:13px>{seniority}</td>
<td style=padding:8px;border-bottom:1px solid #ddd;font-size:12px>{summary}</td>
<td style=padding:8px;border-bottom:1px solid #ddd;font-size:13px>{linkedin_html}</td>
</tr>"""
        profiles_section = f"""<h3 style=color:#1a73e8;margin-top:24px>QA / Testing Profiles Found ({len(profiles)})</h3>
<table cellpadding=0 cellspacing=0 style=border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px>
<tr style=background:#1a73e8;color:#fff><th style=padding:8px;text-align:left>Name / Title</th><th style=padding:8px;text-align:left>Seniority</th><th style=padding:8px;text-align:left>Expertise</th><th style=padding:8px;text-align:left>Profile</th></tr>
{rows}</table>"""

    html = f"""<html><body style=font-family:Arial,sans-serif;color:#222;max-width:600px>
<h2 style=color:#1a73e8>New Lead: {company}</h2>
<table cellpadding=6 cellspacing=0 style=border-collapse:collapse;width:100%>
<tr style=background:#f5f5f5><td><b>Assigned</b></td><td>{rep['name']}</td></tr>
<tr><td><b>Company</b></td><td>{company}</td></tr>
<tr style=background:#f5f5f5><td><b>Email</b></td><td>{lead_info.get("email","")}</td></tr>
<tr><td><b>Industry</b></td><td>{lead_info.get("industry","Unknown")}</td></tr>
<tr style=background:#f5f5f5><td><b>Employees</b></td><td>{emp_range}</td></tr>
<tr><td><b>Accuracy</b></td><td style=color:{acc_color};font-weight:bold>{acc_label}</td></tr>
{sources_row}
<tr style=background:#f5f5f5><td><b>Received</b></td><td>{timestamp}</td></tr>
</table>
{profiles_section}
<br><a href="{zoho_url}" style=background:#1a73e8;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block>Open in Zoho CRM</a>
<p style=font-size:12px;color:#666>QA/Testing profiles via Claude AI web search enrichment.</p></body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"New Lead: {company} -> {rep['name']}"
    msg["From"] = SMTP_FROM
    msg.attach(MIMEText(html, "html"))

    if MODE == "prod":
        msg["To"] = ALERT_RECIPIENT_EMAIL
        recipients = [r.strip() for r in ALERT_RECIPIENT_EMAIL.split(",") if r.strip()]
        tag = "prod"
    else:
        msg["To"] = TEST_EMAIL or "dev@localhost"
        recipients = [TEST_EMAIL.strip()] if TEST_EMAIL else []
        tag = "dev"

    if not recipients:
        logger.warning("[email] lead_id=%s — no recipients, skipping", lead_id)
        return

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())
        logger.info("[email] [%s] sent %s -> %s", tag, lead_id, recipients)
    except Exception as e:
        logger.error("[email] [%s] failed to send %s: %s", tag, lead_id, str(e))
