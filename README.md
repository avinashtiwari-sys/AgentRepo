# GTMFlow

Automated lead qualification and routing pipeline for Zoho CRM.
When a new lead is created in Zoho, GTMFlow validates, enriches, scores, and routes it to the
sales team — then fires an email alert. All heavy work runs asynchronously on a background worker
so the webhook responds in milliseconds.

---

## How it works

```
New Lead in Zoho CRM
        ↓
Webhook → FastAPI server   (verifies token, stores lead, enqueues job, returns 200)
        ↓
Redis queue → RQ worker    (everything below runs in the worker, not the web request)
        ↓
Apollo source?  → Yes: mark SKIPPED, stop (no enrichment, no routing)
        ↓ No
Gate 1 — Domain valid?
  • MX record check
  • Disposable/free email blocklist
  → No: mark INVALID_DOMAIN, stop
        ↓
AI Enrichment (Claude API + web search)
  • Company employee count / range
  • Industry
  • Web presence, competitor check
  • Confidence level (high / med / low)
        ↓
Gate 2 — Company verifiable?
  • Web presence found
  • Not a competitor domain
  → No: mark INVALID_COMPANY, stop
        ↓
Gate 3 — Confidence high or med?
  → Low: mark REVIEW (human review queue), stop
        ↓
Mark MQL_VALID
        ↓
Routing — assign to Sales Team, mark ROUTED
        ↓
Email alert → ALERT_RECIPIENT_EMAIL (comma-separated recipients)
```

> **Note on routing:** the pipeline currently assigns every qualified lead to a single
> "Sales Team" and notifies `ALERT_RECIPIENT_EMAIL`. The earlier per-rep, employee-count-based
> split (SMB vs Enterprise) has been unified. See [app/notify/router.py](app/notify/router.py).

---

## Architecture

GTMFlow runs as **two processes** sharing a database and a Redis instance:

| Process | Command | Responsibility |
|---------|---------|----------------|
| Web server | `uvicorn app.main:app` | Verify webhook, persist lead, enqueue job, return 200 fast. Applies DB migrations on startup. |
| Worker | `rq worker pipeline` | Consume jobs from Redis and run the full enrichment/scoring/routing pipeline. |

Because the pipeline runs out-of-process, a web-server restart never loses an in-flight lead —
the job stays in Redis and is picked up by the worker. Jobs are keyed by `lead:<id>` for
idempotency, so re-delivering the same lead replaces rather than duplicates the work.

---

## Project structure

```
GTMFlow/
├── app/
│   ├── main.py              # FastAPI app, lifespan (config validation + migrations), /health
│   ├── webhook.py           # POST /webhook/zoho — token verify, persist, enqueue
│   ├── logging_config.py    # Rotating file + console logger ("gtmflow")
│   ├── gates/
│   │   ├── domain.py        # Gate 1 — MX + disposable-domain check
│   │   ├── verifier.py      # Gate 2 — web presence + competitor check
│   │   └── confidence.py    # Gate 3 — confidence threshold
│   ├── enrichment/
│   │   └── agent.py         # Claude API web-search enrichment (with retries)
│   └── notify/
│       ├── email.py         # SMTP HTML email alert
│       └── router.py        # Routing + notification trigger
├── workers/
│   ├── queue.py             # RQ queue wiring + enqueue_pipeline()
│   └── pipeline.py          # Full pipeline orchestration (the RQ job)
├── models/
│   ├── lead.py              # Lead SQLAlchemy model + LeadStatus enum
│   └── database.py          # Engine + session (SQLite/Postgres aware)
├── migrations/              # Alembic migrations (env.py + versions/)
├── alembic.ini              # Alembic config (DB URL injected from config.py)
├── config.py                # All env vars + fail-fast validation (only place reading env)
├── pyproject.toml           # Dependencies
├── deploy.sh                # One-command EC2 deployment
├── nginx.conf               # Nginx reverse proxy (HTTP→HTTPS template)
├── test_webhook.py          # Local test script
└── .env.example             # Environment variable template
```

> **Not yet implemented:** the pipeline enriches and routes leads but does **not** write results
> back to Zoho CRM. CRM write-back is a known gap — see the git history for a starting point
> (`app/crm/zoho.py`, removed in cleanup).

---

## Local setup

### 1. Clone the repo

```bash
git clone https://github.com/avinashtiwari-sys/AgentRepo.git GTMFlow
cd GTMFlow
```

### 2. Install dependencies

Using [uv](https://github.com/astral-sh/uv) (recommended — a lockfile is committed):

```bash
uv sync
```

Or with a plain virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configure environment

```bash
cp .env.example .env
nano .env
```

The app **fails fast at boot** if a required var is missing:

| Variable | Required for | Required at boot? |
|----------|-------------|-------------------|
| `ZOHO_WEBHOOK_SECRET` | Webhook auth | **Yes** |
| `ANTHROPIC_API_KEY` | AI enrichment | **Yes** |
| `REDIS_URL` | Async job queue (defaults to `redis://localhost:6379/0`) | No |
| `DATABASE_URL` | DB (defaults to local SQLite) | No |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASSWORD` | Email alerts | No (warns) |
| `ALERT_RECIPIENT_EMAIL` | Email alert recipients | No (warns) |

### 4. Run the server and worker

Migrations run automatically on server startup. You also need Redis running and an RQ worker:

```bash
# terminal 1 — Redis (or use Docker / a managed instance)
redis-server

# terminal 2 — web server (applies migrations on startup)
uv run uvicorn app.main:app --reload

# terminal 3 — background worker
uv run rq worker pipeline
```

### 5. Test with a mock lead

```bash
uv run python test_webhook.py
```

Expected response:
```json
{"status": "accepted", "lead_ids": ["TEST-CONTACT-002"]}
```

The web terminal logs the accepted lead; the worker terminal logs the pipeline stages.

---

## Database & migrations

Schema is managed by **Alembic** — it is the single source of truth (no `create_all`).

- Migrations **auto-apply on web-server startup** and in `deploy.sh`, so fresh deploys and
  restarts are self-healing. You normally never run a migration command by hand.
- `lead.status` is stored as a plain string (not a DB-native enum), so adding a new status value
  needs no `ALTER TYPE`.

When you change a model (add/rename a column), generate a migration once:

```bash
uv run alembic revision --autogenerate -m "describe the change"
# review the new file in migrations/versions/, then it auto-applies on next restart
```

Useful commands:

```bash
uv run alembic upgrade head      # apply all pending migrations
uv run alembic downgrade -1      # roll back the last migration
uv run alembic current           # show the applied revision
```

Default DB is SQLite (`sqlite:///./gtmflow.db`); set `DATABASE_URL` to a `postgresql://` URL for
production. The engine adapts automatically.

---

## Zoho CRM webhook setup

1. In Zoho CRM go to **Settings → Developer Space → Webhooks**
2. Create a new webhook:
   - **URL:** `https://YOUR_DOMAIN/webhook/zoho`
   - **Trigger:** Leads → On Create
   - **Custom Header:**
     - Key: `X-Zoho-Webhook-Token`
     - Value: your `ZOHO_WEBHOOK_SECRET` from `.env`

The webhook carries the shared secret, so it **must be served over HTTPS** in production
(see deployment below). The token is verified with a timing-safe comparison and is never persisted.

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
- Run database migrations (`alembic upgrade head`)
- Register systemd services for the web server + worker
- Configure Nginx
- Print your final webhook URL

### Enable HTTPS

`nginx.conf` ships with an HTTP→HTTPS redirect and a TLS server block. Provision a certificate
with certbot (requires a domain pointing at the instance):

```bash
sudo certbot --nginx -d your-domain.com
```

Until a cert is installed, the plain `:80` block is for local/EC2-IP testing only — do not point a
live Zoho webhook at it.

### AWS Security Group

| Type  | Port | Source |
|-------|------|--------|
| HTTPS | 443  | 0.0.0.0/0 |
| HTTP  | 80   | 0.0.0.0/0 (redirect + ACME challenges) |
| SSH   | 22   | Your IP |

### Health check

```bash
curl https://YOUR_DOMAIN/health
# → {"status": "ok"}
```

---

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ZOHO_WEBHOOK_SECRET` | Shared token set in the Zoho webhook custom header | — (required) |
| `ANTHROPIC_API_KEY` | Claude API key for AI enrichment | — (required) |
| `DATABASE_URL` | SQLite (default) or Postgres connection string | `sqlite:///./gtmflow.db` |
| `REDIS_URL` | Redis URL backing the async RQ job queue | `redis://localhost:6379/0` |
| `SMTP_HOST` | SMTP server hostname | — |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USER` | SMTP login username | — |
| `SMTP_PASSWORD` | SMTP login password | — |
| `SMTP_FROM` | Sender email address | — |
| `ALERT_RECIPIENT_EMAIL` | Comma-separated alert recipients | — |

All config is read in one place — [config.py](config.py). Required vars are validated at startup;
recommended-but-optional vars (SMTP, recipients) log a warning when missing.

---

## Lead status flow

| Status | Meaning |
|--------|---------|
| `received` | Webhook accepted, job enqueued |
| `skipped` | Apollo-sourced lead — pipeline short-circuited, no processing |
| `invalid_domain` | Failed Gate 1 — bad/disposable domain |
| `enriching` | AI enrichment in progress |
| `invalid_company` | Failed Gate 2 — no web presence or competitor |
| `review` | Low confidence — needs human review |
| `mql_valid` | Passed all gates |
| `routed` | Assigned to Sales Team, email sent |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| API server | FastAPI + Uvicorn |
| Background jobs | RQ (Redis Queue) worker |
| AI enrichment | Anthropic Claude API (web search) |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| Migrations | Alembic |
| Email | SMTP via Python smtplib |
| CRM | Zoho CRM (inbound webhook) |
| Web server | Nginx (HTTPS via certbot) |
| Process manager | systemd |
| Dependency mgmt | uv (lockfile committed) |
```

