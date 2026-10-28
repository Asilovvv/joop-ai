#!/usr/bin/env bash
# Back up the Joop AI database (leads, chats, usage) and keep the last 14 copies.
#   sudo bash deploy/backup.sh                 run one backup now
#   sudo bash deploy/backup.sh --install-cron  run it every day at 03:00
set -euo pipefail

APP_DIR=/opt/joop-ai
DB="$APP_DIR/joop.db"
DEST="$APP_DIR/backups"
KEEP=14

if [ "${1:-}" = "--install-cron" ]; then
  echo "0 3 * * * root bash $APP_DIR/deploy/backup.sh >/dev/null 2>&1" > /etc/cron.d/joop-backup
  chmod 644 /etc/cron.d/joop-backup
  echo "Daily backup scheduled at 03:00 (server time) -> $DEST"
  exit 0
fi

[ -f "$DB" ] || { echo "No database at $DB yet"; exit 0; }
mkdir -p "$DEST"
STAMP="$(date +%Y-%m-%d_%H%M)"
# .backup is safe while the bot is running
sqlite3 "$DB" ".backup '$DEST/joop_$STAMP.db'"
chown -R joop:joop "$DEST" 2>/dev/null || true
# Keep only the newest $KEEP backups
ls -1t "$DEST"/joop_*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm --
echo "Backup saved: $DEST/joop_$STAMP.db"
