# Deploying Joop AI to a server (24/7)

On a laptop the bot stops when the laptop sleeps. For pilots with real clients
run it on a small Linux server (VPS). One bot token can be polled by only one
process: **stop the bot on your laptop before starting it on the server**,
otherwise Telegram returns a "Conflict" error.

## 1. Choose a server

Requirements: Ubuntu 22.04 or 24.04, at least 1 GB RAM (512 MB is tight).
Prices below were checked on the providers' official pages on 29 Oct 2026.

| Option | Price / month | RAM | Pays from Kyrgyzstan |
|---|---|---|---|
| [MyHost.kg](https://www.myhost.kg/en/#tab2) VDS-1024 | 1,100 som | 1 GB | Yes: Elkart, MBank, O!Dengi, QR ([payment page](https://www.myhost.kg/oplata.html)) |
| [DigitalOcean](https://www.digitalocean.com/pricing/droplets) Basic | $6 | 1 GB | Card or PayPal; KG not stated |
| [Hetzner Cloud](https://www.hetzner.com/cloud/cost-optimized/) CX23 | €5.99 excl. VAT | 4 GB | Card, PayPal; KG not stated; check stock |
| [Oracle Cloud Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm) | $0 | up to 1 GB (AMD micro) | Credit card required; idle VMs can be reclaimed |

Recommendation for pilots: **MyHost.kg VDS-1024** — local payment, no foreign card.

## 2. Install (about 10 minutes)

On your computer, copy the project to the server (replace `SERVER_IP`):

```bash
cd ~/PycharmProjects
rsync -av --exclude .venv --exclude .env --exclude '*.db' joop-ai/ root@SERVER_IP:/root/joop-ai/
```

On the server:

```bash
ssh root@SERVER_IP
cd /root/joop-ai
sudo bash deploy/install.sh
```

The installer asks for the bot token, the Anthropic API key (input is hidden)
and your chat id, then starts the `joop` service. It restarts automatically
after a crash or a reboot.

Then put the client's profile in place and restart:

```bash
sudo cp /root/joop-ai/business.dental.example.yaml /opt/joop-ai/business.yaml   # or the client's own file
sudo systemctl restart joop
```

## 3. Daily use

| Task | Command |
|---|---|
| Live logs | `journalctl -u joop -f` |
| Status | `systemctl status joop` |
| Restart after editing `business.yaml` | `sudo systemctl restart joop` |
| Daily database backup at 03:00 | `sudo bash /opt/joop-ai/deploy/backup.sh --install-cron` |
| Update the code | copy the new version to `/root/joop-ai`, run `sudo bash deploy/install.sh` again |

Settings, the profile and the database survive updates.

## Docker alternative

If the server already runs Docker: copy `.env` (with `DB_PATH=data/joop.db`)
and `business.yaml` next to `docker-compose.yml`, then `docker compose up -d --build`.

## Several clients

One process per client: copy the project to `/opt/joop-<client>`, give it its
own bot token, `.env`, `business.yaml` and service file (`joop-<client>.service`).
