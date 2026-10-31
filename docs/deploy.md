# First launch on a server

A step-by-step path from an empty server to the first business answering customers. About an hour,
most of it waiting for DNS. Commands are run on the server unless said otherwise.

## 1. What you need

- A Linux server with 2 GB RAM (see the price table in the README; MyHost.kg takes Kyrgyz payment methods).
- A domain, e.g. `joop.kg`, and access to its DNS settings.
- An Anthropic API key **with credit** (console.anthropic.com).
- Your Telegram account, to receive alerts.

## 2. Point the domain at the server

In the domain's DNS settings add an `A` record: name `@` (or a subdomain such as `app`), value = the
server's IP address. Wait until `ping joop.kg` from your computer shows that IP (minutes to a few hours).

## 3. Install Docker and get the code

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/Asilovvv/joop-ai.git && cd joop-ai
cp .env.example .env
```

## 4. Fill in `.env`

Open it with `nano .env`. Required:

| Setting | Value |
| --- | --- |
| `ANTHROPIC_API_KEY` | your key |
| `SESSION_SECRET` | output of `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `TOKEN_ENCRYPTION_KEY` | output of `python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"` (the same format as `python -m joop gen-key`) — **keep a copy outside the server** |
| `DOMAIN` | `joop.kg` |
| `PUBLIC_BASE_URL` | `https://joop.kg` |
| `SECURE_COOKIES` | `true` |

Recommended: `OWNER_PASSWORD` (founder console `/owner`, 12+ characters), `FOUNDER_BOT_TOKEN` and
`FOUNDER_CHAT_ID` (alerts when the AI stops answering), `PRICE_SOM`. Optional: `META_*` for WhatsApp and
Instagram, `ALTEGIO_PARTNER_TOKEN` for salons on Altegio.

## 5. Check, then start

```bash
docker compose build
docker compose run --rm app python -m joop migrate
docker compose run --rm app python -m joop check --live
```

`check` lists every setting as `[OK]`, `[НУЖНО]` (required, with the fix) or `[МОЖНО]` (optional).
`--live` makes one tiny model call (well under a cent) and says plainly if the key is wrong or the balance
is empty. Start only when it ends with «Готово к запуску.»:

```bash
docker compose up -d
```

Caddy gets the HTTPS certificate by itself. Open `https://joop.kg/health`: it should show `{"ok":true}`.

## 6. The first business

Either the owner signs up at `https://joop.kg/signup`, or you create it:

```bash
docker compose run --rm app python -m joop create-business --slug aktish --name "Ак-Тиш Дент"
```

In the panel: fill the price list, hours and FAQ, try the test chat, then «Каналы» → paste the Telegram
bot token → «Подключить Telegram».

## 7. Backups

The server makes one consistent copy of the database a day into `/data/backups` (14 days kept;
`BACKUP_KEEP_DAYS`). It uses SQLite's backup API, because copying the live file can give a broken copy.
A copy on the same server does not survive the server, so once a week take one home:

```bash
docker compose run --rm app python -m joop backup          # a fresh copy now
docker compose cp app:/data/backups/joop-YYYY-MM-DD.db ./  # then download this file with scp or WinSCP
```

Restore: `docker compose stop app`, copy the backup over `/data/joop.db` in the `joop-data` volume,
`docker compose start app`. Encrypted tokens need the same `TOKEN_ENCRYPTION_KEY`.

## 8. Updates and logs

```bash
git pull && docker compose up -d --build   # migrations run on start
docker compose logs -f app                 # what the server is doing
```
