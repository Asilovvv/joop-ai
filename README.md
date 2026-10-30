# Joop AI

*Joop (жооп) means "answer" in Kyrgyz.*

An AI administrator for small businesses in Kyrgyzstan. It answers customers in Telegram,
WhatsApp and Instagram Direct, in Russian or Kyrgyz, quotes prices from the business's own price
list, books customers into real free time slots, reminds them the day before, and hands anything
it cannot handle to staff in Telegram.

One core serves many niches through **niche packs** (`joop/niches/<name>/`): dental clinics, beauty
salons, cafes and restaurants (table booking, orders with code-computed totals, stop list), real
estate (qualified leads, viewings), car services, training centres, wholesale (orders, leads),
fitness clubs, massage and spa, medical centres and labs, veterinary clinics and grooming, driving
schools, hotels and guest houses, tours, photo studios, quest rooms / karaoke / bowling, and dry
cleaning / repair / tailoring.
A pack sets the panel labels, what a conversation can produce (booking, request, order, lead,
handoff), niche rules, optional modules (`features: [level_test]`), demo data and evaluation dialogues. Design: [docs/multi-niche-design.md](docs/multi-niche-design.md).

First market: private dental clinics in Bishkek, where messages that arrive in the evening and at
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
python -m joop create-business --slug demo --name "Demo Dental" --demo   # --niche restaurant | realty | ...
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

## Self-serve sign-up, billing and the founder console

- **Sign-up** at `/signup`: a business picks its niche, gets a sample price list for it and a
  `TRIAL_DAYS` trial. The **launch checklist** (`/panel/setup`) walks it through contacts, price
  list, a **test chat** with its own AI (`/panel/try`), Telegram in one step (paste the BotFather
  token; the webhook is set automatically) and payment.
- **Billing** (`/panel/billing`): `PRICE_SOM` a month by card through FreedomPay Kyrgyzstan, or
  by transfer / QR that the founder confirms. When the trial or the paid month ends (plus 3
  days), the AI stops answering; messages still reach the panel. Businesses created from the
  command line are never blocked.
- **Founder console** (`/owner`, password `OWNER_PASSWORD`): every business with status, usage,
  AI cost and price; monthly revenue; payments waiting for confirmation; actions: open the
  business's panel, +7 days, mark paid, pause, resume, set an individual price.
- **Sales pipeline** (`/owner/prospects`): add businesses or paste a CSV list, let the AI draft a
  personal first message in Russian or Kyrgyz, create a demo account for a prospect in one
  click, and move it through new → contacted → replied → demo → trial → paid. Messages are
  sent by the founder himself: no automatic mass messaging or calls.
- **Partners** (`/owner/partners`): an SMM specialist or agency gets a link `/r/<code>`;
  businesses that sign up through it are attached to the partner, who earns a set percent of
  every payment they make. The partner sees businesses and money owed on a private page
  `/partner/<secret>`; the founder records payouts.
- **Joop Studio** (`/studio`): a business orders a one-page website, an online menu, a price list or
  slides. In `/owner/studio` the AI drafts the site's text from the order (JSON only, rendered by our
  own template, so the model cannot inject HTML), the founder edits and publishes it at `/site/<name>`
  with a WhatsApp button. In the sales pipeline, "Предложить сайт" drafts a first message offering it.
  "Подключить ИИ-администратора" turns the order into a Joop AI company in one click (services and
  prices from the site, trial period started); once its Telegram bot is connected, the founder pastes
  the bot link into "Ссылка на запись" and the site's main button becomes "Записаться через ИИ"
  (only t.me, wa.me and Instagram links are accepted).
- **Level test** (training centres, `/panel/tests`): the school uploads its own questions (CSV: section;
  question; 2-6 options; right answer) and a level scale ("0-10 A1"). In a chat the AI gives the student a
  personal link `/t/<token>`; code (not the model) grades the answers, the result goes back to that chat,
  the school gets a Telegram note and a lead, and the AI then offers groups of that level. A shared link
  `/test/<code>` works for the website, QR codes and Instagram. The panel shows links, finished tests,
  bookings after the test and the conversion. The AI never guesses a level from the chat.
- **QR menu / price list online** (`/panel/menu`): any company can open a phone page `/m/<slug>` built from
  its catalog (categories, prices, stop list, Russian/Kyrgyz names) with an "order" button to its bot or
  WhatsApp, and print a sheet of QR codes, one per table (`/m/<slug>?t=5` shows "Стол 5" and puts the
  table number into the WhatsApp message). Off until the company turns it on.
- **Ratings and coming back** (`/panel/followups`, off by default): two hours after a visit the AI asks
  for a 1-5 rating; 4-5 get a link to leave a review on 2GIS / Google Maps, 1-3 go to the staff at once
  as a handoff. Each service can have "invite again after N days" (manicure 21, cleaning 180): the AI
  invites the customer back unless they have already booked. Messages go only where the channel allows
  (Telegram any time, WhatsApp / Instagram within 24 hours); the rest is listed for the staff.
- **Group classes** (packs with `features: [group_classes]`: fitness, training centres): a resource with
  "Мест в группе" = 12 gets slots that take up to 12 bookings; a claim takes one seat per person atomically
  (`claim_slot(slot, count)`), the slot closes when full, cancelling frees the same seats. The AI sees
  "свободно мест 5 из 12" and offers another class when there are not enough seats.
- **Waitlist**: when the AI takes a booking request without a slot (the wanted time was busy), code puts
  the customer on the waitlist with the day they named. When staff cancel a booking or reopen a slot, the
  first three customers waiting for that day are told in their chat; whoever answers first is booked by
  the AI as usual, so a slot is never promised twice. The list is on the "Записи" page.
- **Passes and packages** (`features: [memberships]`: fitness, spa, beauty, training centres; panel
  "Абонементы"): staff record "10 занятий" with the customer's phone and mark each visit. The AI answers
  "осталось 3 из 10, действует до 30.11" only to a chat it can trust with that phone (the WhatsApp number
  itself, or a chat with a past visit); otherwise it names no numbers and hands over to staff.
- **Order status** (`features: [jobs]`: dry cleaning / repair / tailoring pack `repair`, car services;
  panel "Заказы в работе"): staff record what was left, with a receipt number and phone, and change the
  status. The AI answers "готово?" only for a job tied to the customer — the WhatsApp number itself, or the
  receipt number together with the phone given at drop-off. Marking a job ready messages the customer.
- **Weekly report**: every Monday, with the morning summary, the owner gets the week in numbers:
  customers answered, how many outside working hours, bookings, requests and orders.

## Database migrations

The schema is managed with Alembic (`joop/migrations`). The server applies pending migrations on
start; `python -m joop migrate` does it by hand. After changing a model, generate a migration with
`python -m joop make-migration "what changed"`, review it, and commit it with the model change:
a test fails when models and migrations differ. Back up the database file before upgrading a live
server.

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
python -m pytest          # 106 tests: engine, niches, orders, migrations, channels, panel, webhooks, evaluation
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

Every niche pack has its own set (12–13 dialogues, at least 4 in Kyrgyz):

```bash
python -m eval.run_eval restaurant     # or: dental, beauty, realty, auto, education, wholesale, all
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
- Channel tokens are encrypted in the database when `TOKEN_ENCRYPTION_KEY` is set
  (`python -m joop gen-key`, then `python -m joop encrypt-tokens` for tokens saved earlier).
  Keep a copy of the key apart from the database backups: a lost key means reconnecting every channel.
- Customers cannot cancel or reschedule by themselves yet: the AI passes such requests to staff.
- The service stores patient names, phone numbers and what they wrote. Agree with each business in
  writing how this data is processed and stored, as personal data rules require.
