# GTMFlow

Automated lead qualification and routing pipeline for Zoho CRM.  
When a new lead is created in Zoho, GTMFlow validates, enriches, scores, and routes it to the right sales rep — then fires an email alert.

---

## How it works

```
New Lead in Zoho CRM
        ↓
Webhook → FastAPI server
        ↓
Gate 1 — Domain valid?
  • MX record check
  • Disposable/free email blocklist
  → No: mark INVALID, stop
        ↓
AI Enrichment (Claude API + web search)
  • Company employee count
  • Industry
  • Confidence level (high / med / low)
        ↓
Gate 2 — Company verifiable?
  • Web presence found
  • Not a competitor domain
  → No: mark INVALID, stop
        ↓
Gate 3 — Confidence high or med?
  → Low: park in human review queue
        ↓
Mark MQL Valid
        ↓
Routing — Employee count
  • < 250 → Preksha (SMB / Mid-Market)
  • > 250 → Srini / Anuja (Enterprise, round-robin)
        ↓
Email alert → PcloudySalesMarketing@opkey.com
```

---

## Project structure

```
GTMFlow/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── webhook.py           # POST /webhook/zoho handler
│   ├── gates/
│   │   ├── domain.py        # Gate 1 — domain validation
│   │   ├── verifier.py      # Gate 2 — company verification
│   │   └── confidence.py    # Gate 3 — confidence threshold
│   ├── enrichment/
│   │   └── agent.py         # Claude AI web search enrichment
│   ├── crm/
│   │   └── zoho.py          # Zoho CRM REST API client
│   └── notify/
│       ├── email.py         # SMTP email alert
│       └── router.py        # Routing logic + notification trigger
├── workers/
│   └── pipeline.py          # Full pipeline orchestration
├── models/
│   ├── lead.py              # Lead DB model + status enum
│   └── database.py          # SQLAlchemy engine + session
├── config.py                # All env vars in one place
├── requirements.txt
├── deploy.sh                # One-command EC2 deployment
├── nginx.conf               # Nginx reverse proxy config
├── test_webhook.py          # Local test script
└── .env.example             # Environment variable template
```

---

## Local setup

### 1. Clone the repo

```bash
git clone https://github.com/avinashtiwari-sys/AgentRepo.git GTMFlow
cd GTMFlow
```

### 2. Create virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
nano .env
```

Fill in at minimum:

| Variable | Required for |
|----------|-------------|
| `ANTHROPIC_API_KEY` | AI enrichment |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | Email alerts |
| `ZOHO_WEBHOOK_SECRET` | Webhook auth (can leave blank locally) |

### 4. Run the server

```bash
uvicorn app.main:app --reload
```

### 5. Test with a mock lead

```bash
python test_webhook.py
```

Expected response:
```json
{"status": "accepted", "lead_ids": ["TEST-LEAD-001"]}
```

Pipeline logs will appear in the server terminal.

---

## Zoho CRM webhook setup

1. In Zoho CRM go to **Settings → Developer Space → Webhooks**
2. Create a new webhook:
   - **URL:** `http://YOUR_SERVER/webhook/zoho`
   - **Trigger:** Leads → On Create
   - **Custom Header:**
     - Key: `X-Zoho-Webhook-Token`
     - Value: your `ZOHO_WEBHOOK_SECRET` from `.env`

---

## AWS deployment

### Upload and deploy

```bash
# From your local machine
scp -i your-key.pem ~/path/to/gtmflow.zip ec2-user@YOUR_EC2_IP:~/

# On the EC2 instance
unzip gtmflow.zip && cd GTMFlow
bash deploy.sh
```

The deploy script will:
- Install Python, Redis, Nginx
- Create a `.env` file (pauses for you to fill it in)
- Register systemd services for web server + worker
- Configure Nginx on port 80
- Print your final webhook URL

### AWS Security Group

| Type | Port | Source |
|------|------|--------|
| HTTP | 80 | 0.0.0.0/0 |
| SSH  | 22 | Your IP |

### Health check

```bash
curl http://YOUR_EC2_IP/health
# → {"status": "ok"}
```

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `ZOHO_WEBHOOK_SECRET` | Shared token set in Zoho webhook custom header |
| `ZOHO_CLIENT_ID` | Zoho OAuth client ID |
| `ZOHO_CLIENT_SECRET` | Zoho OAuth client secret |
| `ZOHO_REFRESH_TOKEN` | Zoho OAuth refresh token |
| `ANTHROPIC_API_KEY` | Claude API key for AI enrichment |
| `DATABASE_URL` | SQLite (default) or Postgres connection string |
| `SMTP_HOST` | SMTP server hostname |
| `SMTP_PORT` | SMTP port (default: 587) |
| `SMTP_USER` | SMTP login username |
| `SMTP_PASSWORD` | SMTP login password |
| `SMTP_FROM` | Sender email address |
| `REP_PREKSHA_EMAIL` | SMB rep email |
| `REP_SRINI_EMAIL` | Enterprise rep 1 email |
| `REP_ANUJA_EMAIL` | Enterprise rep 2 email |

---

## Lead status flow

| Status | Meaning |
|--------|---------|
| `received` | Webhook accepted, pipeline starting |
| `invalid_domain` | Failed Gate 1 — bad/disposable domain |
| `enriching` | AI enrichment in progress |
| `invalid_company` | Failed Gate 2 — no web presence or competitor |
| `review` | Low confidence — needs human review |
| `mql_valid` | Passed all gates |
| `routed` | Assigned to rep, email sent |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| API server | FastAPI + Uvicorn |
| Background jobs | FastAPI BackgroundTasks |
| AI enrichment | Anthropic Claude API (web search) |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Email | SMTP via Python smtplib |
| CRM | Zoho CRM REST API |
| Web server | Nginx |
| Process manager | systemd |
