# Joop AI

*Joop (жооп) means "answer" in Kyrgyz.*

An AI administrator for small businesses in Kyrgyzstan. It answers customers in Telegram,
WhatsApp and Instagram Direct, in Russian or Kyrgyz, quotes prices from the business's own price
list, books customers into real free time slots, reminds them the day before, and hands anything
it cannot handle to staff in Telegram.

First niche: private dental clinics in Bishkek, where messages that arrive in the evening and at
weekends often go unanswered until the next working day.

## What a business gets

- Replies within seconds at any hour, including nights and weekends.
- Bookings only into free slots, checked by code. Two customers can never get the same slot.
- A Telegram message to staff for every new booking and every request the AI escalates.
- Reminders the day before the appointment and a morning summary for staff.
- A web panel: price list, specialists, FAQ, time slots, bookings, conversations and pilot numbers.
- Staff can take over any conversation, and the AI steps aside.
- Kyrgyz and Russian: the reply follows the customer's language; a language guard rewrites a
  Russian reply to a Kyrgyz message, and services can carry Kyrgyz names.
- Businesses without a schedule in the panel still get bookings: the AI takes a request (name,
  phone, service, preferred time) and staff call back to confirm.
- Cost tracking: tokens and USD per AI reply, shown in the panel.

## Quick start on your computer (about 10 minutes)

You need Python 3.11 or newer and a Claude API key from https://platform.claude.com.

```bash
git clone <this repository> joop-ai && cd joop-ai
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                 # then put ANTHROPIC_API_KEY and SESSION_SECRET into .env
python -m joop create-business --slug demo --name "Demo Dental" --demo
python -m joop chat --slug demo      # talk to the AI in the terminal as a patient
```

`--demo` adds a sample price list, three specialists and a week of free slots. Replace them with
real data in the panel.

A client's price list, FAQ and rules can also come from a YAML profile (format:
[business.dental.example.yaml](business.dental.example.yaml)):

```bash
python -m joop create-business --slug aktish --profile clients/aktish.yaml
python -m joop import-profile --slug aktish --file clients/aktish.yaml   # update later
```

### Telegram bot without a server

1. In Telegram, open @BotFather, send `/newbot`, copy the token.
2. Run `python -m joop dev --slug demo` and open http://127.0.0.1:8000/login (login `demo`).
3. Open "Каналы", paste the token, save. Message your bot from your phone: it answers.
4. Open "Настройки" and send the shown `/admin <code>` to the bot: booking notifications will
   arrive in that chat. Add the bot to a staff group and send the code there to notify everyone.

`dev` mode polls Telegram, so it needs no public address. For WhatsApp and Instagram you need a
server with HTTPS.

## Deploy to a server

You need a small Linux server (2 GB RAM is enough for several businesses), a domain name pointing
to it, and Docker.

| Server | Price / month | RAM | Pays from Kyrgyzstan |
|---|---|---|---|
| [MyHost.kg](https://www.myhost.kg/en/) VDS-KVM-2G | 1,600 som | 2 GB | Yes: Elkart, MBank, O!Dengi, QR ([payment page](https://www.myhost.kg/oplata.html)) |
| [DigitalOcean](https://www.digitalocean.com/pricing/droplets) Basic | $12 | 2 GB | Card or PayPal |
| [Hetzner Cloud](https://www.hetzner.com/cloud/) CX23 | €5.99 incl. IPv4, excl. VAT | 4 GB | Card or PayPal; often out of stock |

Prices checked on the providers' pages on 29 October 2026.

```bash
git clone <this repository> joop-ai && cd joop-ai
cp .env.example .env
# fill in: ANTHROPIC_API_KEY, SESSION_SECRET, DOMAIN=joop.example.kg,
# PUBLIC_BASE_URL=https://joop.example.kg, SECURE_COOKIES=true,
# META_VERIFY_TOKEN and META_APP_SECRET if you connect WhatsApp or Instagram
docker compose up -d --build
docker compose run --rm app python -m joop create-business --slug aktish --name "Ак-Тиш Дент"
```

Caddy obtains the HTTPS certificate automatically. The panel is at `https://<DOMAIN>/login`. In
"Каналы", the "Подключить Telegram" button registers the bot's webhook.

Backups: the database is one file in the `joop-data` volume:
`docker compose cp app:/data/joop.db ./joop-$(date +%F).db`.

## Connecting WhatsApp and Instagram

Telegram works the same day. WhatsApp works the same day on a new number the business owns.
Keeping the clinic's existing WhatsApp Business app number, and answering real patients on
Instagram, both require Meta Business Verification and App Review (plan 2–5 weeks). Instagram
reminders are possible only within 24 hours of the patient's last message.

Step-by-step setup, the webhook address and the WhatsApp reminder template:
[docs/channels.md](docs/channels.md).

## Costs

See [docs/pilot-economics.md](docs/pilot-economics.md). In short: the AI itself costs well under
100 som per clinic per month at current Claude Haiku 5.5 prices. The main costs are the server and
WhatsApp message fees for reminders.

## Configuration

All settings are environment variables; see [.env.example](.env.example).

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `JOOP_MODEL` | Model for replies, default `claude-haiku-5-5` |
| `JOOP_THINKING`, `JOOP_EFFORT` | Thinking mode (`disabled` for speed) and effort level |
| `SESSION_SECRET` | Signs panel login cookies; any long random string |
| `PUBLIC_BASE_URL` | `https://` address of the server, for webhooks |
| `META_VERIFY_TOKEN`, `META_APP_SECRET` | Meta webhook verification and signature check |
| `DATABASE_URL` | SQLite by default; Postgres works with a driver such as `psycopg` |
| `SCHEDULER_ENABLED` | Reminders and morning summary |

## Development

```bash
python -m pytest          # 75 tests: engine, channels, scheduler, panel, webhooks, evaluation
```

The tests use a fake model and fake channels, so they need no keys or network.

## Evaluation with the real model

Scripted conversations check grounding, Kyrgyz replies, booking capture, escalation, medical
safety and prompt-injection resistance:

| Profile | Cases |
|---|---|
| [business.example.yaml](business.example.yaml) (beauty studio) | [eval/cases.yaml](eval/cases.yaml), 24 |
| [business.dental.example.yaml](business.dental.example.yaml) (dental clinic) | [eval/cases_dental.yaml](eval/cases_dental.yaml), 14 |

```bash
python -m eval.run_eval business.dental.example.yaml eval/cases_dental.yaml eval/results_dental.json
```

The run prints pass/fail per case, average and maximum reply time, cost per conversation and how
often the language guard fired, and saves everything to a JSON file. On GitHub, Actions → eval →
Run workflow does the same with the repository secret `ANTHROPIC_API_KEY` and keeps results on the
`eval-results` branch. On macOS, double-click `eval.command`. Have a native speaker review the
Kyrgyz cases and the `name_ky` values before reporting results.
How the parts fit together: [docs/architecture.md](docs/architecture.md).

## Known limitations

- The fixed replies for voice notes and errors are in Kyrgyz and Russian; the Kyrgyz wording needs
  a native speaker's check.
- Voice notes: the AI asks the customer to write and sends the voice note to staff as a request.
  Speech-to-text is not built yet; Kyrgyz recognition quality must be tested first (see the
  economics doc).
- One panel login per business; no staff roles and no login attempt limit yet.
- Channel tokens are stored in the database unencrypted: protect the server and its backups.
- Customers cannot cancel or reschedule by themselves yet: the AI passes such requests to staff.
- The service stores patient names, phone numbers and what they wrote. Agree with each business in
  writing how this data is processed and stored, as personal data rules require.
