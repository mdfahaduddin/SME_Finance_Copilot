#!/bin/sh
# Nightly PostgreSQL backup. Run from the directory containing docker-compose.yml:
#   ./deploy/backup.sh                    -> backups/smecopilot-YYYYmmdd-HHMMSS.sql.gz
# Cron example (02:30 every night):
#   30 2 * * * cd /opt/smecopilot && ./deploy/backup.sh >> backups/backup.log 2>&1
# Copy the backups directory off the server (e.g. rclone / object storage) - a backup that
# lives only on the same disk is not a backup.
set -eu

KEEP_DAYS="${KEEP_DAYS:-14}"
DIR="${BACKUP_DIR:-backups}"
mkdir -p "$DIR"
FILE="$DIR/smecopilot-$(date +%Y%m%d-%H%M%S).sql.gz"

# --clean --if-exists makes the dump restorable over an existing database.
docker compose exec -T db pg_dump -U smecopilot -d smecopilot --clean --if-exists --no-owner \
  | gzip -9 > "$FILE.partial"
mv "$FILE.partial" "$FILE"
echo "$(date -Is) backup written: $FILE ($(du -h "$FILE" | cut -f1))"

# Retention: only removes this script's own old backup files.
find "$DIR" -name 'smecopilot-*.sql.gz' -mtime +"$KEEP_DAYS" -print -delete
