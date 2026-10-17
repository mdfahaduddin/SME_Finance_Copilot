#!/bin/sh
# serve      apply migrations, refresh the product catalogue, start the API
# scheduler  run daily maintenance (expired sessions / tokens) forever
# anything else is executed as-is, e.g. `python -m app.cli check`
set -e

case "$1" in
  serve)
    alembic upgrade head
    python -m app.cli seed-products
    # Only the reverse proxy can reach this port (it is not published), so trusting its
    # X-Forwarded-For header is safe and gives rate limiting the real client IP.
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      --workers "${WEB_CONCURRENCY:-2}" \
      --proxy-headers --forwarded-allow-ips '*' \
      --no-server-header
    ;;
  scheduler)
    while true; do
      python -m app.cli prune || echo "prune failed" >&2
      sleep 86400
    done
    ;;
  *)
    exec "$@"
    ;;
esac
