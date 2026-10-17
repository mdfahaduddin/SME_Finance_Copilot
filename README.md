# SME Finance Copilot

An AI finance copilot for small-business owners. It analyses finances, forecasts cash flow with alerts, matches financing options, and takes actions only with human approval.

Businesses sign up, add their bank accounts and import bank statements (PDF, including scanned statements read with on-server OCR, CSV or Excel), invoices and bills (CSV or Excel). PDF statements are checked line by line against the printed running balance before anything is saved. The copilot works from that data. It never moves money or contacts anyone on its own: approved actions are recorded for the owner to complete.

Every business works in its own currency (USD, BDT, EUR, INR and more): amounts, financing comparisons, cash-flow scenarios and approval limits are all shown and enforced in that currency. Reports can be filtered by period and downloaded as CSV, Excel or a lender-ready PDF summary.

**Repository:** https://github.com/mdfahaduddin/SME_Finance_Copilot

## For judges: FinTechathon 2026

**2026 Shenzhen International FinTech Competition, WeBank International Track, Topic E: SME Finance Copilot.** Theme: *AI as a Financial Participant*.

### Run it in about 10 minutes

You need Python 3.12+ and Node.js 20+. No AI key, database server or internet account is needed: the database is a local file with a ready-made demo business, and without an OpenAI key the copilot answers in offline mode from the same finance engines.

**Terminal 1 (backend and database)**, Windows PowerShell:

```powershell
git clone https://github.com/mdfahaduddin/SME_Finance_Copilot.git
cd SME_Finance_Copilot\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m seed.seed
uvicorn app.main:app --port 8000
```

On macOS/Linux use `python3 -m venv .venv`, `source .venv/bin/activate` and `cp .env.example .env`.

**Terminal 2 (frontend):**

```bash
cd SME_Finance_Copilot/frontend
npm install
npm run dev
```

Open **http://localhost:5500** and sign in as `owner@lotusbakery.example` / `Owner#2026`. Other roles and the full guide: [Run the demo locally](#run-the-demo-locally) and [Troubleshooting](#troubleshooting).

### What to try (mapped to the scoring criteria)

**Task completion (40%)**
1. **Dashboard:** health score, 13-week cash forecast with a cash squeeze about six weeks out, and alerts.
2. **Copilot:** ask *"Will I run out of cash in the next 3 months?"* or *"Can I afford a $45,000 oven in late November?"* and watch the agent choose its tools.
3. **Financing:** compare $45,000 for Equipment; every option shows cost, fit, approval odds and why, and excluded products say why not.
4. **Cash Flow:** tick *One-off purchase* and *Take a loan*, then **Run scenario**.
5. **Data:** import a bank statement (PDF, CSV or Excel); PDF rows are checked against the printed running balance.
6. **Reports:** filter by period and download the profit and loss, cash-flow forecast, aged receivables or transactions as CSV or Excel, and the two-page **Financial summary (PDF)** for a lender.

**Security and compliance (30%)**
1. In the copilot ask *"Who owes me money? Remind the most overdue customer."*: the agent can only create an **approval request**; nothing happens until a person approves it.
2. On **Financing**, request an application: approving it requires the owner's **password** (high-value action).
3. Sign in as `viewer@lotusbakery.example` / `Viewer#2026`: read-only, no action tools.
4. **Audit Log:** "Hash chain intact"; every login, tool call and decision is recorded.
5. One invoice memo contains a hidden prompt-injection telling the AI to move money: the agent flags and ignores it.

**Innovation and interaction (30%)**
- Every figure in an answer is checked against the engines' results (*"8/8 figures verified"*); names and account numbers are masked before reaching the AI.
- Scanned PDF statements are read with on-server OCR and imported only when the running balance confirms each row.
- Multi-currency: change **Settings → Business profile → Currency** to BDT and the whole app, including financing criteria and approval limits, switches to taka.

**Tests:** backend: `cd backend` then `pytest` (about 236 tests, 2-3 minutes, no key or network needed). Frontend: `cd frontend` then `npm test` (42 tests, under a minute).

### Submission deliverables

| Requirement | Where |
|---|---|
| Technical documentation (architecture, algorithms, security design) | [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md) |
| Presentation deck (10 minutes or less) | [docs/deck/](docs/deck/) |
| Demo video (5 minutes or less) | see [docs/EXECUTION_EVIDENCE.md](docs/EXECUTION_EVIDENCE.md#demo-video) |
| Source code, README, deployment instructions, tests | this repository; [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md); `backend/tests/` (pytest) and `frontend/src/**/*.test.tsx` (Vitest); reports in [docs/evidence/](docs/evidence/) |
| Security self-assessment (permission tiers, known risks) | [docs/SECURITY_SELF_ASSESSMENT.md](docs/SECURITY_SELF_ASSESSMENT.md) |
| Execution evidence (sandbox operation logs) | [docs/EXECUTION_EVIDENCE.md](docs/EXECUTION_EVIDENCE.md) and [docs/evidence/](docs/evidence/) |

All lenders, customers and the demo business are fictional. The sandbox never moves money or sends email: approved actions are recorded for a person to complete.

## Contents

- [Run the demo locally](#run-the-demo-locally) (database, backend, frontend: about 10 minutes)
- [Database](#database) (reset, empty database, upgrading after a `git pull`, PostgreSQL)
- [Optional features](#optional-features) (AI key, scanned-PDF OCR, exchange rates)
- [Production deployment](#production-deployment) (live server: Docker, PostgreSQL, HTTPS)
- [Troubleshooting](#troubleshooting)
- [Demo data and logins](#demo-data-local-development-only)
- [Deploying to a server](docs/DEPLOYMENT.md) (Docker Compose, PostgreSQL, automatic HTTPS, backups)

## Documentation

| Document | Contents |
|---|---|
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Server setup, configuration, backups, updates, operations, local trial of the Docker stack |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | A 5-minute walkthrough of the main features |
| [docs/TECHNICAL_DOCUMENTATION.md](docs/TECHNICAL_DOCUMENTATION.md) | Architecture, finance engines, agent design |
| [docs/SECURITY_SELF_ASSESSMENT.md](docs/SECURITY_SELF_ASSESSMENT.md) | Permission tiers, threat model, known risks |
| [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) | Dependency licenses |

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Python 3.14, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL (SQLite for local development), Redis, pandas, statsmodels, pdfplumber, Tesseract OCR |
| AI agent | OpenAI Responses API with function calling (`gpt-6-luna` by default); offline rule-based fallback when no key is set or the provider fails |
| Frontend | React 19, TypeScript, Vite, **Tailwind CSS v4**, Recharts, lucide-react |
| Tests | pytest (backend), Vitest + React Testing Library (frontend) |
| Deployment | Docker Compose: Caddy (automatic HTTPS), API, PostgreSQL 17, Redis 7 |

## Run the demo locally

You need two terminals: one for the backend (port 8000) and one for the frontend (port 5500). The local database is a single SQLite file, so there is no database server to install.

### Prerequisites

| Tool | Version | Check with |
|---|---|---|
| Python | 3.12 or newer (developed on 3.14) | `python --version` |
| Node.js | 20 or newer | `node --version` |
| Git | any | `git --version` |
| Tesseract OCR | optional, only for scanned (image) PDF statements | `tesseract --version` |

### 1. Get the code

```bash
git clone https://github.com/mdfahaduddin/SME_Finance_Copilot.git
cd SME_Finance_Copilot
```

### 2. Backend and database

**Windows (PowerShell):**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # copy the output into .env as SECRET_KEY=...
python -m seed.seed                 # creates data\smecopilot.db with the demo business
uvicorn app.main:app --reload --port 8000
```

**macOS / Linux:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # copy the output into .env as SECRET_KEY=...
python -m seed.seed                 # creates data/smecopilot.db with the demo business
uvicorn app.main:app --reload --port 8000
```

- `SECRET_KEY` is optional locally. Without it a random key is used on each start, so everyone is signed out whenever the backend restarts.
- `OPENAI_API_KEY` is optional. Without it the copilot runs in **offline mode** (rule-based answers from the same finance engines), so the whole demo works without an AI account.
- Check the backend: http://localhost:8000/api/health should return `{"status":"ok"}`. API docs are at http://localhost:8000/docs.

Leave this terminal running.

### 3. Frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env.local          # Windows: copy .env.example .env.local
```

To show one-click demo logins on the sign-in page, open `frontend/.env.local` and set `VITE_DEMO_MODE=true`. Then:

```bash
npm run dev
```

Open **http://localhost:5500**. The frontend forwards `/api` requests to the backend on port 8000.

### 4. Sign in

Sign in with a [demo login](#demo-logins-local-demo-database-only) (for example `owner@lotusbakery.example` / `Owner#2026`), or click **Create an account** to register a new, empty business and go through onboarding (add a bank account, import a statement).

To try importing, use a PDF or CSV statement from any bank, or download a sample layout with the **Template** button on the **Data** page.

Without SMTP settings, password-reset and invitation emails are not sent: they are printed to the backend terminal, links included.

### 5. Tests (optional)

```bash
cd backend
pytest              # about 236 tests in 2-3 minutes; no API key or network needed (OCR tests skip without Tesseract)
```

```bash
cd frontend
npm test            # 42 tests (Vitest + React Testing Library) in under a minute
```

## Database

Local development uses SQLite: one file, `backend/data/smecopilot.db` (set by `DATABASE_URL` in `backend/.env`). Production uses PostgreSQL ([docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).

| Task | Command (from `backend/`, with the virtual environment active) |
|---|---|
| Create or **reset** the demo database (deletes all local data) | `python -m seed.seed` |
| Pin the demo dates (repeatable demos) | `python -m seed.seed --as-of 2026-10-13` |
| Create an **empty** database instead (no demo business) | `alembic upgrade head` then `python -m app.cli seed-products` |
| **After a `git pull`**: apply new database changes, keeping your data | `alembic upgrade head` |
| See which migration the database is at | `alembic current` |
| Check configuration, database and OCR | `python -m app.cli check` |
| Back up the local database | copy `data/smecopilot.db` somewhere safe (stop the backend first) |

Always run `alembic upgrade head` after pulling new code. If the backend logs **"DATABASE SCHEMA IS OUT OF DATE"**, or pages fail with *Internal server error* and the log mentions a missing column, that step was skipped.

**Using PostgreSQL locally:** create a database, set `DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/smecopilot` in `backend/.env`, then run `alembic upgrade head` and `python -m app.cli seed-products`. The demo seeder refuses to run against PostgreSQL unless you add `--force`, because it deletes every table.

## Optional features

| Feature | How to enable |
|---|---|
| **AI answers** (instead of offline mode) | Set `OPENAI_API_KEY` in `backend/.env` and restart the backend. Settings → AI copilot shows *Online* when it is used. |
| **Scanned PDF statements** (OCR) | Install Tesseract. **Windows:** the [UB Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki), then set `TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe` in `backend/.env`. **macOS:** `brew install tesseract`. **Ubuntu/Debian:** `sudo apt install tesseract-ocr`. Text-based PDFs, CSV and Excel work without it. For Bengali statements add the `ben` language pack and set `OCR_LANGUAGES=eng+ben`. |
| **Exchange rates** | Financing compares lender criteria (set in USD) in the business currency at indicative rates, and approval limits are converted the same way. Override a rate with `FX_RATES={"BDT": 121.5}` in `backend/.env`. |
| **Real emails** | Set the `SMTP_*` values in `backend/.env`. |
| **Demo logins on the sign-in page** | `VITE_DEMO_MODE=true` in `frontend/.env.local` (never in production builds). |

## Production deployment

The live product runs on one Linux server with Docker Compose: **Caddy** (automatic HTTPS, serves the app), the **API**, **PostgreSQL 17**, **Redis** and a small scheduler. The full guide, with configuration reference, backups, updates and a security checklist, is [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). In short:

1. **Server:** Ubuntu 24.04 (2 vCPU, 4 GB RAM), Docker with the Compose plugin, a domain whose DNS points at the server, ports 80 and 443 open.
2. **Get the code and configure it:**
   ```bash
   git clone https://github.com/mdfahaduddin/SME_Finance_Copilot.git /opt/smecopilot
   cd /opt/smecopilot
   cp .env.production.example .env
   openssl rand -hex 32        # paste as POSTGRES_PASSWORD in .env
   openssl rand -base64 48     # paste as SECRET_KEY in .env
   nano .env                   # set DOMAIN (and optionally OPENAI_API_KEY, SMTP_*)
   ```
3. **Start it:**
   ```bash
   docker compose up -d --build
   docker compose ps           # "api" becomes healthy within about a minute
   ```
   On every start the API applies database migrations and loads the lender catalogue. Caddy obtains the HTTPS certificate automatically.
4. **Use it:** open `https://<your domain>` and choose **Create an account**. The demo business and demo logins are **not** created in production; real businesses register and import their own statements.
5. **Back up:** `deploy/backup.sh` (daily, from cron); restore with `deploy/restore.sh`. **Update:** `git pull` then `docker compose up -d --build`.

| | Local demo | Production |
|---|---|---|
| Database | SQLite file `backend/data/smecopilot.db` | PostgreSQL 17 in Docker (enforced: production refuses to start on SQLite) |
| Data | Demo business from `python -m seed.seed` | Empty; businesses register |
| Address | http://localhost:5500 | https://your-domain (automatic certificate) |
| Config | `backend/.env` | `.env` in the project root (from `.env.production.example`) |

**Try the production stack on your own machine** (no domain needed): `cp .env.production.example .env`, set `DOMAIN=localhost` and the two secrets, run `docker compose up -d --build`, then open https://localhost and accept the self-signed certificate warning. `docker compose down -v` removes the trial **and deletes its database**.

## Troubleshooting

| Problem | Fix |
|---|---|
| *Internal server error* on the dashboard or other pages; the backend log says "no such column" or "SCHEMA IS OUT OF DATE" | From `backend/`: `alembic upgrade head`, then reload the page. |
| `alembic upgrade head` fails with "table ... already exists" | The database was created by an older version of `seed.seed` that did not record migrations. Either reset the demo data with `python -m seed.seed`, or keep your data: `alembic stamp 9d7a81007930` then `alembic upgrade head` (back up `data/smecopilot.db` first). |
| The frontend shows network errors or *502* | The backend is not running on port 8000. Start it (step 2) and check http://localhost:8000/api/health. |
| Signed out every time the backend restarts | Set a 32+ character `SECRET_KEY` in `backend/.env`. |
| Port 5500 or 8000 already in use | Stop the other program, or run the backend on another port (`--port 8001`) and point the frontend at it: `API_PROXY=http://localhost:8001 npm run dev` (PowerShell: `$env:API_PROXY="http://localhost:8001"; npm run dev`). |
| Vite's port is "not permitted" on Windows | Hyper-V reserves ports 5153–5352 on some machines; this project uses 5500 for that reason. |
| A scanned PDF imports no rows ("scanned images and could not be read") | Install Tesseract and set `TESSERACT_CMD` (see [Optional features](#optional-features)), then restart the backend. `python -m app.cli check` shows whether OCR is available. |
| The copilot says it is in offline mode | Expected without `OPENAI_API_KEY`. With a key, check the backend log for provider errors. |
| `python` not found on Windows | Install Python from python.org and tick *Add python.exe to PATH*, or use `py` instead of `python`. |

## Security model (summary)

| Control | Implementation |
|---|---|
| Authentication | Server-side sessions in an HttpOnly, Secure, SameSite cookie (60 min idle / 12 h absolute); signed double-submit CSRF token; bcrypt; optional TOTP two-factor; password reset by email; sessions revoked on password change |
| Abuse protection | Redis-backed rate limits on sign-in, registration, recovery, 2FA, chat, imports and actions |
| Authorisation | Roles enforced server-side on every route: owner, accountant, viewer |
| Human-in-the-loop | Payments, reminders, deferral requests and loan applications are queued as requests; only allowed roles can approve; requests expire after 24h |
| Re-authentication | Approving any action of $5,000 or more (or the equivalent in the business currency, e.g. BDT 610,000) requires the approver's password |
| Limits | Scheduled payments capped at $10k each and $25k per day, converted into the business currency (BDT 1.2M and 3M) |
| Integrity | Amounts are read from the referenced records, unknown parameters rejected, each request executes at most once |
| Audit | Append-only SHA-256 hash chain (`GET /api/audit/verify` detects edits/deletions); parameters stored as hashes, no customer PII |
| AI agent | Tools limited by role (viewers get no action tools); action tools only create approval requests; max 3 per turn, 8 steps per turn |
| LLM privacy | Names, emails, account and phone numbers replaced by tokens before reaching the provider; `store=false`; hashed user id only |
| Prompt injection | Third-party text (invoice memos) wrapped as untrusted and flagged; no money-moving tool exists; human approval still required |
| Hallucination | All figures come from engines; every number in an answer is checked against tool results and untraceable ones are reported |
| Hardening | Only last 4 digits of accounts stored, CSP/HSTS and security headers, body limits (5 MB for imports), CORS restricted to the app origin, API docs disabled in production, fail-fast production config |

## Demo data (local development only)

`python -m seed.seed` resets the local SQLite database (it refuses to run in production or against PostgreSQL without `--force`) and loads **Lotus Bakery & Cafe Ltd.**, a fictional 2-location bakery with about $1.2M annual revenue. It includes:
- 18 months of transactions
- B2B catering invoices
- supplier bills
- an existing term loan
- a 14-product mock lender marketplace (fictional lenders, criteria in USD)

The data is deterministic: the same `--seed` and `--as-of` always produce the same data. Dates are relative to today by default. Pass `--as-of YYYY-MM-DD` to pin them.

Built-in scenarios the copilot should detect:
- **Late-paying client:** Riverside Hotel Group pays later every month and has invoices more than 30 days overdue.
- **Cash squeeze about 6 weeks out:** an annual insurance premium and a bulk holiday flour order fall in the same window as rent and payroll.
- **Expense anomaly:** a $6,850 oven repair about 4 months ago.
- **Seasonality:** a December peak and a January–February trough.
- **Prompt-injection test:** one invoice memo contains a hidden instruction asking the AI to move money. The agent must ignore it.

To see the app in another currency, sign in as the owner and change **Settings → Business profile → Currency** (for example to BDT).

### Demo logins (local demo database only)

| Role | Email | Password |
|---|---|---|
| Owner (can approve actions) | owner@lotusbakery.example | Owner#2026 |
| Accountant | accountant@lotusbakery.example | Accountant#2026 |
| Viewer (read-only) | viewer@lotusbakery.example | Viewer#2026 |

**One-click demo logins:** to show **Owner / Accountant / Viewer** buttons on the sign-in page that fill in these logins, create `frontend/.env.local` (copy `frontend/.env.example`) with:

```
VITE_DEMO_MODE=true
```

Then restart the frontend (`npm run dev`); Vite reads env files only at startup.
- It only shows the buttons. The accounts themselves come from `python -m seed.seed`, so seed the database first.
- Without it, the logins above still work when typed in by hand.
- `.env.local` is ignored by git, and production builds always turn demo mode off, so the buttons never appear on a live site.

## Project structure

```
backend/
  app/            FastAPI app: config, db, models, sessions/RBAC (auth.py), security, audit (hash chain),
                  actions (approval queue), importer, PDF statements + OCR, fx (currency conversion)
  app/api/        REST routers: auth, onboarding (profile, accounts, team), data_import, insights, ledger, governance, chat
  app/agent/      copilot agent: tools (T0/T1/T2), orchestrator, PII masker, guardrails, prompts, LLM client, offline fallback
  app/engines/    deterministic finance engines (analysis, forecast, alerts, matching, scenario)
  migrations/     Alembic database migrations
  seed/           demo data generator, lender catalogue
  scripts/        smoke test, evidence generator
  tests/          pytest suite
frontend/
  src/components  reusable Tailwind components, layout, chat, data import, settings
  src/pages       Dashboard, Copilot, Cash Flow, Financing, Approvals, Data, Team, Audit, Settings, Sign in, Register, Onboarding
  Dockerfile      builds the app and serves it with Caddy (Caddyfile)
deploy/           backup.sh, restore.sh
docker-compose.yml, .env.production.example   production stack
```
