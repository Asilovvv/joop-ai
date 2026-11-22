# First launch on a server

A step-by-step path from an empty server to the first business answering customers. About an hour,
most of it waiting for DNS. Commands are run on the server unless said otherwise.

## Fast path: one script

After step 2 below (the domain points to the server), on the server:

```bash
curl -fsSL https://raw.githubusercontent.com/Asilovvv/joop-ai/main/deploy/setup.sh -o setup.sh
sudo bash setup.sh
```

It asks three questions: the domain, the model key — Anthropic (`sk-ant-…`) or Google Gemini (`AIza…`; then
also the model id, Enter for `gemini-3.8-flash`; on real customers use Gemini's paid tier, see
`docs/model-providers.md`) — the subscription price (Enter to decide later),
and, optionally, a Telegram bot token for your outage alerts (then it asks you to message the bot and finds
your chat id itself). It does steps 3–5 for you: installs Docker and git, gets the code into `/opt/joop-ai`,
writes `.env` (mode 600) with a fresh `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEY` and founder console password,
warns if DNS does not point to this server yet, builds, migrates, runs `check --live` (stops with the fix if
the key is wrong or the balance is empty), starts and waits for HTTPS. At the end it prints the sign-up and
`/owner` addresses and the console password. Running it again keeps `.env` and only updates and restarts.

Then continue with step 6. The steps below are the same work by hand.

## 1. What you need

- A Linux server with 2 GB RAM (see the price table in the README; MyHost.kg takes Kyrgyz payment methods).
- A domain, e.g. `joop.kg`, and access to its DNS settings.
- An Anthropic API key **with credit** (console.anthropic.com), or a Google Gemini API key on a paid tier
  (aistudio.google.com).
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
`FOUNDER_CHAT_ID` (alerts when the AI stops answering, and a note when it answers again), `PRICE_SOM`. Optional: `META_*` for WhatsApp and
Instagram, `ALTEGIO_PARTNER_TOKEN` for salons on Altegio, `STT_PROVIDER=elevenlabs` and `STT_API_KEY` to
answer voice messages (otherwise they go to staff).

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
docker compose run --rm app python -m joop create-business --slug aktish --name "Ак-Тиш Дент" --password 'пароль-панели'
```

(`--password` is required here: `docker compose run` has no terminal to ask for it. Pick 8+ characters and
pass it to the owner; they can change it in «Настройки».) The command prints the `/admin` code for Telegram
notifications. Once the business's bot is connected, the owner does not need it: «Запуск» and «Настройки» show a
«Подключить уведомления» button that opens the bot and links that Telegram in one tap (the code then changes, so a
code someone else saw no longer works).

In the panel: fill the price list, hours and FAQ, try the test chat, then «Каналы» (or «Запуск») → paste the Telegram
bot token → «Подключить Telegram».

## 7. Backups

The server makes one consistent copy of the database a day into `/data/backups` (14 days kept;
`BACKUP_KEEP_DAYS`). It uses SQLite's backup API, because copying the live file can give a broken copy.
A copy on the same server does not survive the server. When the founder bot is set up (`FOUNDER_BOT_TOKEN`,
`FOUNDER_CHAT_ID`), each daily copy also arrives in that chat as a file `joop-YYYY-MM-DD.db.gz.enc`, silently:
compressed and encrypted with `TOKEN_ENCRYPTION_KEY`, so customers' names and phones never leave the server in the
clear. Turn it off with `BACKUP_TO_TELEGRAM=false`. A database above 50 MB does not fit in Telegram; the bot then
says so and the weekly download below is the off-site copy.

To restore from such a file, on any machine with the code and the same `TOKEN_ENCRYPTION_KEY` in `.env`:

```bash
python -m joop restore-copy joop-2026-11-03.db.gz.enc --out joop-2026-11-03.db
```

then put that `.db` back as shown under «Restore» below. Without the key the file cannot be read by anyone,
including you: keep the key outside the server.

Without the founder bot, take a copy home once a week:

```bash
docker compose run --rm app python -m joop backup          # a fresh copy now
docker compose cp app:/data/backups/joop-YYYY-MM-DD.db ./  # then download this file with scp or WinSCP
```

Restore (the copy you took home is `joop-2026-11-03.db`, say):

```bash
docker compose stop app
docker compose cp ./joop-2026-11-03.db app:/data/joop.db
docker compose run --rm --user root app chown -R joop /data   # the copy arrives as root; the app runs as joop
docker compose start app
curl -s https://<your domain>/health                           # {"ok":true}
```

Without the `chown` line the panel opens and logins work, but every write fails: the AI answers nobody.
`/health` and `python -m joop check` say so («нет записи в файл базы»), and the uptime alert (section 8) fires.

Encrypted channel tokens need the same `TOKEN_ENCRYPTION_KEY` as when the copy was made.

On 22 November 2026 the Docker path itself was rehearsed: the image built, `migrate` and `check` on an empty
database, sign-up through the site, then an upgrade of that data from the 8 November version (schema 0049) to the
current one (0067) in the same volume with every row kept, a login with the old password, all 25 panel pages,
`backup`, and a restore of the encrypted Telegram copy. The restore found the missing `chown` above.

This guide was run end to end on a clean machine on 3 November 2026 and again on 8 November 2026 (fresh clone at
PR #132, a plain Python environment with the same commands — the test machine could not pull images from Docker
Hub, so `docker compose build` itself was not exercised there). Checked: `migrate` on an empty database (to 0047),
`check` (only the Anthropic key reported missing), `create-business`, `serve` with `/health`, sign-up, every panel
section, `backup` and a restored copy (`integrity_check` ok), and an upgrade of a 1 November database (schema 0016)
to 0047 in one run, repeated without changes, with no foreign-key errors and all data kept.

## 8. Alert when the whole server is down

The server tells you when the AI stops answering, but not when the server itself is gone (machine off, disk full,
domain or certificate expired). A GitHub check does that from outside, every 10 minutes, for free:

1. On GitHub: **Settings → Secrets and variables → Actions → Variables → New repository variable**:
   `JOOP_URL` = `https://joop.kg` (your `PUBLIC_BASE_URL`).
2. Same page, **Secrets**: `FOUNDER_BOT_TOKEN` and `FOUNDER_CHAT_ID` with the values from the server's `.env`.
3. **Actions → uptime → Run workflow** once to see it pass.

You get one Telegram message when `/health` stops answering (with the reason in words) and one when it is back.
GitHub may run the check a few minutes late, and pauses scheduled checks after 60 days without commits: then
**Actions → uptime → Enable workflow**.

## 9. Updates and logs

```bash
git pull && docker compose up -d --build   # migrations run on start
docker compose logs -f app                 # what the server is doing
```

## 10. The mobile app

The owner's and the customers' app (Flutter, `mobile/`) talks to this server's `/api/mobile/…`. A release is an
Android APK attached to a GitHub Release, built for your domain and signed with your own key.

### The app's signing key

Once, before the first release; about 10 minutes. A phone installs an update only when it is signed with the same
key as the installed app, so the key is made once, stays with the owner, and signs every release.

1. Make the keystore. `keytool` comes with Android Studio and with any Java:

   ```bash
   mkdir -p ~/joop-signing && cd ~/joop-signing
   keytool -genkeypair -keystore joop-release.jks -alias joop -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Joop AI"
   ```

   It asks for a new password twice (6 characters or more): choose one and write it down. On a Mac with Android
   Studio and no separate Java, type `"/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/keytool"`
   in place of `keytool`.
2. On GitHub: **Settings → Secrets and variables → Actions → New repository secret**, two secrets:
   - `ANDROID_KEYSTORE_BASE64`: the keystore file as text. `base64 -i joop-release.jks | pbcopy` copies it on a Mac
     (Linux: `base64 -w0 joop-release.jks`; Windows PowerShell:
     `[Convert]::ToBase64String([IO.File]::ReadAllBytes("joop-release.jks")) | Set-Clipboard`); paste it as the value.
   - `ANDROID_KEYSTORE_PASSWORD`: the password from step 1.
3. Keep `~/joop-signing/joop-release.jks` and the password in two places of your own (a password manager, a flash
   drive). GitHub never shows a secret again, and without the key no update can be installed over the app:
   everyone would have to remove it and install it anew.

Never commit the keystore or its password: the repository is public (`mobile/android/.gitignore` ignores `*.jks`
and `key.properties`). A keystore made long ago whose key has its own name or password: put them into the secrets
`ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`.

### A release

When the server answers `https://joop.kg/health`:

1. On GitHub: **Actions → mobile-release → Run workflow**.
2. `version`: `mobile-v1.0.0` (the phone shows 1.0.0; the next one is `mobile-v1.0.1` or `mobile-v1.1.0`).
   `api_url`: `https://joop.kg`, the server's `PUBLIC_BASE_URL`; leave it empty when the repository variable
   `JOOP_URL` (section 8) is set.
3. The workflow stops at once, saying what to fix, when the signing key is not in the secrets, the password does
   not open it, the server does not answer (`/health`, and `/api/mobile/login` with a wrong password gives 401), or
   the key is not the one the previous release was signed with. Otherwise it builds the APK, checks its signature
   and attaches it to a GitHub Release with that tag. The release notes record the build number and the key's
   certificate; the next release is compared with them, and its build number is always higher.

`https://github.com/<owner>/<repository>/releases/latest/download/joop-ai.apk` always gives the newest release:
a lasting link for the site, a message or a QR code. Owners install the APK and sign in with the company login and
panel password; customers open a business by its code (the slug in its `/c/<slug>` link). A new version installs
over the old one, and nobody signs in again.

If the keystore is lost for good, make a new one and run the workflow with **new_key** ticked: the release notes
then tell everyone to remove the app before installing. To try the app before any of this, take the APK from the
latest **Actions → mobile** run (`mobile/README.md`): on its sign-in screen «Другой сервер» takes the address by
hand, but that build is signed with a one-run key and cannot be updated. iOS needs an Apple developer account and
is not built here.
