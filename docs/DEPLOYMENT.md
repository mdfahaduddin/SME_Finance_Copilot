# Deployment guide

SME Finance Copilot runs as five containers on one Linux server (VPS), started with Docker Compose:

```
Internet ──443/80──▶ web (Caddy)  ── HTTPS, static React app, security headers
                         │ /api/*
                         ▼
                     api (FastAPI, uvicorn workers) ──▶ db (PostgreSQL 17)
                         │                          └─▶ redis (rate limits)
                     scheduler (daily cleanup of expired sessions and tokens)
```

Only Caddy publishes ports. The API, database and Redis are reachable only on the internal Docker network.

## 1. Server requirements

- Ubuntu 24.04 LTS (or any Linux with Docker), **2 vCPU / 4 GB RAM** minimum, 20 GB disk
- Docker Engine 27+ with the Compose plugin: https://docs.docker.com/engine/install/ubuntu/
- A domain name (for example `finance.example.com`) with an **A record** (and AAAA for IPv6) pointing at the server
- Firewall: allow inbound **22** (SSH), **80** and **443** (TCP), plus **443/UDP** for HTTP/3. Block everything else.

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443 && sudo ufw enable
```

## 2. First deployment

```bash
sudo mkdir -p /opt/smecopilot && sudo chown $USER /opt/smecopilot
git clone https://github.com/mdfahaduddin/SME_Finance_Copilot.git /opt/smecopilot
cd /opt/smecopilot
cp .env.production.example .env
chmod 600 .env
nano .env        # set DOMAIN, POSTGRES_PASSWORD, SECRET_KEY (and optionally OPENAI_API_KEY, SMTP_*)
```

Generate the two secrets:

```bash
openssl rand -hex 32        # POSTGRES_PASSWORD
openssl rand -base64 48     # SECRET_KEY
```

Start the stack:

```bash
docker compose up -d --build
docker compose ps           # api should become "healthy" within about a minute
```

On every start the API container:
1. applies database migrations (`alembic upgrade head`)
2. loads or updates the lender product catalogue (`python -m app.cli seed-products`, idempotent)
3. starts uvicorn with `WEB_CONCURRENCY` workers

Caddy requests a Let's Encrypt certificate for `DOMAIN` the first time it starts. That needs DNS already pointing at the server and port 80 open.

Open `https://<DOMAIN>` and choose **Create a business account**. The first user of each business becomes its owner and can invite the team from **Team**.

### Checks

```bash
curl https://<DOMAIN>/api/ready                     # {"status":"ready","productCatalog":true,"env":"production"}
docker compose exec api python -m app.cli check     # configuration summary (no secrets)
docker compose logs -f api                          # JSON logs, one line per request, with request IDs
```

The API refuses to start in production if `SECRET_KEY` is missing or short, if `DATABASE_URL` is not PostgreSQL, or if `PUBLIC_BASE_URL` is not `https://`. The error appears in `docker compose logs api`.

## 3. Configuration reference

All settings live in `/opt/smecopilot/.env`. After changing it, run `docker compose up -d` to apply.

| Variable | Required | Purpose |
|---|---|---|
| `DOMAIN` | yes | Public host name. Used for the TLS certificate, emailed links and CORS |
| `POSTGRES_PASSWORD` | yes | Database password (hex, because it is embedded in a URL) |
| `SECRET_KEY` | yes | Signs CSRF tokens and encrypts 2FA secrets. **Changing it signs everyone out and breaks existing 2FA enrolments** |
| `OPENAI_API_KEY` | no | Enables the AI copilot. Without it, the copilot runs in offline rule-based mode |
| `OPENAI_MODEL` | no | Default `gpt-6-luna` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | recommended | Password-reset and invitation emails. Without SMTP the links only appear in the API log |
| `SENTRY_DSN` | no | Error tracking (no cookies, headers or emails are sent) |
| `WEB_CONCURRENCY` | no | API worker processes. Default 2; about 1 per CPU core |
| `LOG_LEVEL` | no | Default `INFO` |

Fixed in `docker-compose.yml`: `APP_ENV=production`, Secure cookies, JSON logs, Redis-backed rate limits, and `CORS_ORIGINS` / `PUBLIC_BASE_URL` derived from `DOMAIN`.

### Scanned statements (OCR)

Scanned PDF statements are read on the server with Tesseract OCR, which the API image includes. Statement images never leave the server. OCR results are only imported where the statement's running balance confirms them. Rows that can't be confirmed are listed for the user to check, and unreadable scans are refused with a request for a clearer scan (300 dpi recommended).

- English is built in. For other languages, set `OCR_LANGS=ben` (Tesseract pack names) and `OCR_LANGUAGES=eng+ben` in `.env`, then rebuild with `docker compose up -d --build`.
- OCR is CPU-heavy: about 3-5 seconds per page. At most `OCR_CONCURRENCY` pages (default 2) are processed at once per API worker, and scans are limited to `OCR_MAX_PAGES` (default 30).
- `docker compose exec api python -m app.cli check` shows `ocr=on` when Tesseract is working.

## 4. Backups

`deploy/backup.sh` writes a compressed `pg_dump` to `backups/` and deletes its own backups older than 14 days (`KEEP_DAYS`).

```bash
chmod +x deploy/*.sh
./deploy/backup.sh
crontab -e
# 30 2 * * * cd /opt/smecopilot && ./deploy/backup.sh >> backups/backup.log 2>&1
```

**Copy backups off the server** (for example `rclone sync backups remote:smecopilot-backups` in the same cron line). A backup stored only on the same disk is lost along with that disk.

### Restore

`deploy/restore.sh` **replaces all current data** with the backup. It asks you to type `RESTORE`, stops the API while it runs, and restarts it afterwards.

```bash
./deploy/restore.sh backups/smecopilot-20261013-023000.sql.gz
```

Test a restore on a separate machine at least once, before you need one.

## 5. Updating

```bash
cd /opt/smecopilot
./deploy/backup.sh                 # always back up before an update
git pull
docker compose up -d --build       # migrations run automatically on start
docker compose ps
```

To roll back the code: `git checkout <previous-commit>` then `docker compose up -d --build`. If the update included a database migration, restore the pre-update backup as well.

## 6. Operations

| Task | Command |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f api` (or `web`, `db`, `scheduler`) |
| Find one request | `docker compose logs api \| grep <requestId>` (the ID is in every error response and `X-Request-ID` header) |
| Restart the API | `docker compose restart api` |
| Database shell | `docker compose exec db psql -U smecopilot` |
| Clean expired sessions now | `docker compose exec api python -m app.cli prune` (the scheduler does this daily) |
| Verify the audit chain | Audit Log page → **Verify chain**, or `GET /api/audit/verify` |
| Disk usage | `docker system df` and `du -sh backups` |

Uptime monitoring: point an external monitor (UptimeRobot, Better Stack and similar) at `https://<DOMAIN>/api/ready`. It returns 503 when the database is unreachable or the schema is out of date.

## 7. Security checklist

- [ ] `.env` is `chmod 600` and never committed
- [ ] SSH: key-only login (`PasswordAuthentication no`), root login disabled
- [ ] Firewall allows only 22, 80, 443
- [ ] Automatic security updates: `sudo apt install unattended-upgrades`
- [ ] SMTP configured, so password resets and invites actually reach users
- [ ] Owners enable two-factor authentication (Settings → Security)
- [ ] Nightly backups copied off the server, and one restore tested
- [ ] External uptime monitor on `/api/ready`
- [ ] (Optional) `SENTRY_DSN` set for error alerts

## 8. Limitations to know before going live

- **No bank or lender integrations.** Data comes from imports: PDF bank statements (downloaded or scanned; phone photos usually aren't clear enough) and CSV/Excel. Approved actions are *recorded*: reminder and deferral emails are prepared in the outbox for the user to send, scheduled payments must still be made in the bank, and financing applications are prepared, not submitted.
- **Lender catalogue.** `backend/seed/products.py` holds an illustrative product list. Replace it with real, verified products before showing financing matches to customers. `seed-products` updates rows matched by lender and product name.
- **Single server.** Fine for many small businesses. For high availability, move PostgreSQL to a managed service (set `DATABASE_URL` accordingly) and run several API instances behind a load balancer.
- **Regulation.** Analysis and financing comparisons are decision support, not regulated financial advice. Check local requirements (data protection, financial promotions) for your market.

## Local trial of the production stack

To try the full stack on your own machine without a domain:

```bash
cp .env.production.example .env    # set DOMAIN=localhost and the two secrets
docker compose up -d --build
```

Then open https://localhost. Caddy uses a self-signed certificate for `localhost`, so the browser shows a warning to accept. Remove the trial with `docker compose down -v`, which **deletes the trial database**.
