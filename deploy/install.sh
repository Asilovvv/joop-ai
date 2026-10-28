#!/usr/bin/env bash
# Install or update Joop AI as a systemd service on Ubuntu 22.04/24.04.
# Run as root from the project folder copied to the server:
#   sudo bash deploy/install.sh
# Safe to run again after an update: keeps .env, business.yaml and the database.
set -euo pipefail

APP_DIR=/opt/joop-ai
APP_USER=joop
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run as root: sudo bash deploy/install.sh" >&2
  exit 1
fi

echo "1/6 System packages"
apt-get update -qq
apt-get install -y -qq python3 python3-venv sqlite3 rsync >/dev/null

echo "2/6 Service user"
id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"

echo "3/6 Copy code to $APP_DIR (keeps .env, business.yaml, *.db, backups)"
mkdir -p "$APP_DIR"
rsync -a --exclude '.git' --exclude '.venv' --exclude '.env' --exclude '*.db' \
  --exclude 'business.yaml' --exclude 'backups' --exclude '__pycache__' \
  "$SRC_DIR/" "$APP_DIR/"
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "4/6 Python environment"
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "5/6 Settings"
cd "$APP_DIR"
if ! sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m joop.setup --check; then
  # Interactive: asks for the bot token, API key and owner chat id (input hidden)
  sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m joop.setup
fi
chmod 600 "$APP_DIR/.env"
if [ ! -f "$APP_DIR/business.yaml" ]; then
  # Demo profile until the client's own file is copied in
  sudo -u "$APP_USER" cp "$APP_DIR/business.example.yaml" "$APP_DIR/business.yaml"
  echo "Created business.yaml from the demo profile: replace it with the client's data."
fi

echo "6/6 systemd service"
install -m 644 "$APP_DIR/deploy/joop.service" /etc/systemd/system/joop.service
systemctl daemon-reload
systemctl enable --now joop.service
systemctl restart joop.service
sleep 3
systemctl --no-pager --lines=5 status joop.service || true

echo
echo "Done. Logs: journalctl -u joop -f"
echo "Daily database backup: sudo bash $APP_DIR/deploy/backup.sh --install-cron"
