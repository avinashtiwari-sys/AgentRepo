import smtplib
import ssl
from datetime import datetime, timezone
from typing import List
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
        links = "".join(f'<li><a href="{s}">{s[:40]}...</a></li>' for s in sources)
        sources_row = f"<tr><td><b>Sources</b></td><td><ul style=padding-left:16px;margin:0>{links}</ul></td></tr>"

    # Search queries (from Gemini grounding metadata — shows what was searched)
    search_queries = lead_info.get("_search_queries", [])
    queries_row = ""
    if search_queries:
        qlist = "".join(f"<li>{q}</li>" for q in search_queries)
        queries_row = f"<tr style=background:#f5f5f5><td><b>Searches</b></td><td><ul style=padding-left:16px;margin:0;font-size:12px;color:#555>{qlist}</ul></td></tr>"

    profiles = lead_info.get("profiles", [])
    profiles_section = ""
    if profiles:
        p = profiles[0]
        linkedin = p.get("linkedin", "")
        name = p.get("name", "Unknown")
        title = p.get("title", "")
        summary = p.get("summary", "")
        if linkedin and linkedin.lower() != "unknown":
            linkedin_html = f'<a href="{linkedin}" style=color:#1a73e8>LinkedIn Profile</a>'
        else:
            linkedin_html = "N/A"
        profiles_section = f"""<h3 style=color:#1a73e8;margin-top:24px>Lead Contact</h3>
<table cellpadding=8 cellspacing=0 style=border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px;background:#f9f9f9;border:1px solid #ddd>
<tr><td style=font-weight:bold;width:100px>{name}</td><td style=font-size:12px;color:#666>{title}</td><td style=font-size:12px>{summary[:200]}</td><td style=font-size:13px>{linkedin_html}</td></tr>
</table>"""

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
{queries_row}
<tr style=background:#f5f5f5><td><b>Received</b></td><td>{timestamp}</td></tr>
</table>
{profiles_section}
<br><a href="{zoho_url}" style=background:#1a73e8;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block>Open in Zoho CRM</a>
<p style=font-size:12px;color:#666>Lead enrichment via AI web search.</p></body></html>"""

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


def send_balance_alert(results: List[dict]):
    """Send an email alert when one or more service balances are low.

    Parameters
    ----------
    results : List[dict]
        Output of ``check_all_balances()``, filtered to ``status == "low"``.
    """
    if not SMTP_HOST or not SMTP_USER:
        logger.warning("[email] SMTP not configured — skipping balance alert")
        return

    # Determine recipients
    if MODE == "prod":
        recipients = [r.strip() for r in ALERT_RECIPIENT_EMAIL.split(",") if r.strip()]
        tag = "prod"
    else:
        recipients = [TEST_EMAIL.strip()] if TEST_EMAIL else []
        tag = "dev"

    if not recipients:
        logger.warning("[email] balance alert — no recipients, skipping")
        return

    # Build the email body
    rows = ""
    for r in results:
        service = r["service"]
        msg = r.get("message", "No details")
        remaining = r.get("remaining")
        balance = r.get("balance")

        if remaining is not None:
            detail = f"<b>{remaining}</b> credits remaining"
        elif balance is not None:
            detail = f"<b>${balance:.2f}</b> remaining"
        else:
            detail = "No balance info available"

        color = "#dc3545" if r.get("status") == "low" else "#856404"
        rows += f"""<tr style="background:{'#fff3f3' if r.get('status') == 'low' else '#fff'};">
    <td style="padding:10px;border:1px solid #ddd;font-weight:bold;color:{color};">{service}</td>
    <td style="padding:10px;border:1px solid #ddd;color:{color};">⚠ LOW</td>
    <td style="padding:10px;border:1px solid #ddd;">{detail}</td>
    <td style="padding:10px;border:1px solid #ddd;font-size:12px;color:#666;">{msg}</td>
</tr>"""

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#222;max-width:600px;margin:0 auto;">
<h2 style="color:#dc3545;">⚠ Service Balance Alert</h2>
<p>One or more paid services are running low on credits. Please top up before the service is interrupted.</p>
<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px;">
<tr style="background:#f8f8f8;">
    <th style="padding:10px;border:1px solid #ddd;text-align:left;">Service</th>
    <th style="padding:10px;border:1px solid #ddd;text-align:left;">Status</th>
    <th style="padding:10px;border:1px solid #ddd;text-align:left;">Remaining</th>
    <th style="padding:10px;border:1px solid #ddd;text-align:left;">Details</th>
</tr>
{rows}
</table>
<br>
<p style="font-size:12px;color:#666;">
    <b>GTMFlow</b> — automatic balance monitoring<br>
    Generated at {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}
</p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "⚠ GTMFlow — Low Balance Alert"
    msg["From"] = SMTP_FROM
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, recipients, msg.as_string())
        logger.info("[email] [%s] balance alert sent -> %s", tag, recipients)
    except Exception as e:
        logger.error("[email] [%s] balance alert failed: %s", tag, str(e))
