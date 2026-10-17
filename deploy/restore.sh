#!/bin/sh
# Restore a backup made by backup.sh. THIS REPLACES ALL CURRENT DATA in the database.
#   ./deploy/restore.sh backups/smecopilot-20261013-023000.sql.gz
set -eu

FILE="${1:?usage: restore.sh <backup.sql.gz>}"
[ -f "$FILE" ] || { echo "No such file: $FILE" >&2; exit 1; }

echo "This will overwrite every table in the production database with: $FILE"
printf "Type RESTORE to continue: "
read -r answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

# Stop writers first so nothing changes mid-restore.
docker compose stop api scheduler
gunzip -c "$FILE" | docker compose exec -T db psql -U smecopilot -d smecopilot -v ON_ERROR_STOP=1 --quiet
docker compose start api scheduler
echo "Restore complete."
