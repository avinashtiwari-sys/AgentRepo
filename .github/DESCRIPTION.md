# GTMFlow: Automated Lead Qualification & Routing

GTMFlow is a high-performance, automated pipeline designed to streamline lead management for Zoho CRM. It intercepts new lead creations via webhooks and subjects them to a rigorous multi-stage validation and enrichment process before routing them to the appropriate sales teams.

## Core Pipeline Stages

1.  **Gate 1: Domain Validation**: Checks for valid MX records and filters out disposable or free email providers.
2.  **AI Enrichment**: Utilizes Anthropic's Claude API to perform web searches and extract critical company data such as employee count and industry.
3.  **Gate 2: Company Verification**: Verifies the company's web presence and ensures it is not a known competitor.
4.  **Gate 3: Confidence Scoring**: Filters leads based on the AI's confidence level (High/Medium required).
5.  **Automated Routing**: Assigns leads to specific sales representatives based on company size (SMB/Mid-Market vs. Enterprise).
6.  **Notification**: Triggers real-time email alerts to the sales team upon successful routing.

## Technology Stack

-   **Backend**: FastAPI, Uvicorn
-   **AI**: Anthropic Claude API
-   **Database**: SQLAlchemy (SQLite/PostgreSQL)
-   **Integration**: Zoho CRM REST API
-   **Infrastructure**: Nginx, systemd, AWS (EC2)

## Lead Lifecycle

Leads progress through various statuses: `received` -> `enriching` -> `mql_valid` -> `routed`. Failure at any gate results in `invalid_domain`, `invalid_company`, or `review` status.
