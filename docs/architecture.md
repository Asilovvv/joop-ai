# Architecture

Joop AI is one Python service. It receives customer messages from messaging channels, lets a
language model draft the reply, checks every action the model proposes against the database, and
shows the business what happened in a web panel.

## Components

```mermaid
flowchart LR
    subgraph Channels
        TG[Telegram Bot API]
        WA[WhatsApp Cloud API]
        IG[Instagram API]
    end
    subgraph Service["Joop AI service (FastAPI)"]
        WH[Webhooks<br/>secret / signature check]
        DP[Dispatcher]
        EN[Reply engine]
        PB[Prompt builder]
        VAL[Booking validation<br/>atomic slot claim]
        SCH[Scheduler<br/>reminders, morning summary]
        PNL[Admin panel]
    end
    LLM[Claude Haiku 5.5<br/>structured JSON output]
    DB[(SQLite / Postgres)]
    ADM[Clinic staff<br/>Telegram chat]

    TG & WA & IG --> WH --> DP --> EN
    EN --> PB --> LLM --> EN
    EN --> VAL --> DB
    EN --> DB
    DP -->|reply| TG & WA & IG
    DP -->|new booking, lead| ADM
    SCH --> DB
    SCH -->|reminder| TG & WA & IG
    SCH -->|summary| ADM
    PNL <--> DB
```

## One message, end to end

```mermaid
sequenceDiagram
    participant C as Customer
    participant Ch as Channel (WhatsApp)
    participant W as Webhook
    participant E as Engine
    participant M as Claude
    participant D as Database
    participant A as Staff chat

    C->>Ch: "Болит зуб, можно завтра?"
    Ch->>W: POST /webhooks/meta (signed)
    W->>W: verify X-Hub-Signature-256
    W-->>Ch: 200 EVENT_RECEIVED (immediately)
    W->>E: background task
    E->>D: dedupe by message id, store message
    E->>D: load price list, staff, free slots, last 20 messages
    E->>M: system prompt + history
    M-->>E: {"reply", "booking", "handoff"}
    alt booking proposed
        E->>D: UPDATE slot SET booked WHERE id=? AND status='free'
        alt slot claimed
            E->>D: insert booking
            E->>A: "Новая запись через ИИ ..."
        else slot already taken
            E->>E: replace reply with free alternatives
        end
    end
    E->>D: store reply
    E->>Ch: send reply
    Ch->>C: reply
```

## Data model

```mermaid
erDiagram
    BUSINESS ||--o{ SERVICE : "price list"
    BUSINESS ||--o{ STAFF : employs
    BUSINESS ||--o{ FAQ : answers
    BUSINESS ||--o{ SLOT : offers
    STAFF ||--o{ SLOT : "works in"
    BUSINESS ||--o{ CONVERSATION : has
    CONVERSATION ||--o{ MESSAGE : contains
    SLOT ||--o| BOOKING : "taken by"
    CONVERSATION ||--o{ BOOKING : produces
    CONVERSATION ||--o{ LEAD : escalates
```

Every table carries `business_id`, so one deployment serves many businesses (multi-tenant).

## Design decisions

1. **The model proposes, the code decides.** The model returns JSON with an optional `booking`. The
   engine books only if the slot exists, belongs to this business, is in the future and is still
   free. The claim is one conditional `UPDATE`, so two customers can never get the same slot. If the
   check fails, the customer gets real alternatives instead of the model's confirmation.
2. **Structured output with a safety net.** Requests ask for a JSON schema. If the API rejects an
   optional setting, the client drops it and retries, and the parser also accepts JSON inside text.
   A failed call never leaves the customer without an answer: they get a fallback message and staff
   get a lead. When the model answers again, customers still waiting (no staff reply, request still
   open, at most 12 hours, Telegram/WhatsApp/Instagram) get a real answer that starts with an apology
   for the delay, and their requests are closed (`joop/recovery.py`).
3. **Staff can take over.** When a clinic replies by hand from its own Instagram or WhatsApp app,
   the channel sends an "echo". Echoes that match our own replies are ignored; any other echo pauses
   the AI in that conversation for 12 hours. Staff can also pause or resume the AI in the panel.
4. **At-least-once webhooks, exactly-once replies.** Channels retry deliveries. Every stored message
   keeps its channel message id, and a repeated id is dropped before any work is done.
5. **Off-hours is measured, not guessed.** Each message and booking records whether it arrived
   outside the business's working hours. That is the pilot's headline number: how many customers
   were served while nobody was at the desk.
6. **Secrets stay on the server.** Channel tokens are write-only in the panel, never logged, and
   request URLs that contain the Telegram token are not logged either. Meta webhooks are rejected
   unless their signature matches the app secret.
7. **Time convention.** `*_at` columns are UTC; slot and booking start times are the business's
   local time. The business timezone is a setting (default Asia/Bishkek).

## Code map

| Path | Responsibility |
|---|---|
| **Conversation core** | |
| `joop/agent/prompt.py` | System prompt from the business's data; message history mapping |
| `joop/agent/llm.py` | Claude client, response schema per niche, tolerant JSON parsing |
| `joop/agent/engine.py` | One message in: commands, media, pause, model call, checks of every booking, order and lead, language and confirmation guards |
| `joop/dispatch.py` | Runs the engine in a DB session, then delivers the reply and staff notes |
| `joop/channels/` | Telegram, WhatsApp and Instagram parsing and send clients; Telegram polling |
| `joop/lang.py`, `joop/kyrgyz.py` | Kyrgyz/Russian heuristics; Kyrgyz drafts of service names and FAQ |
| `joop/slots.py`, `joop/stays.py` | Time slots with an atomic claim; hotel nights booked atomically |
| **Niches and modules** | |
| `joop/niches/<name>/` | Niche packs: labels, outcomes, rules, demo data, evaluation dialogues |
| `joop/placement.py`, `joop/memberships.py`, `joop/jobs.py`, `joop/waitlist.py`, `joop/intake.py` | Level tests, passes, order status, waiting list, questions before a visit |
| `joop/followups.py`, `joop/faq_gaps.py` | Ratings and return invitations; questions handed to staff as FAQ candidates |
| `joop/web/accounts.py` | Staff logins (`PanelUser`); owner-only sections are listed in `app.py` (`OWNER_ONLY`) |
| `joop/staff_reply.py` | Staff reply from the panel through the customer's channel; web chat updates |
| `joop/nudges.py` | Reminders to staff about requests nobody answered |
| `joop/autofill.py`, `joop/web/autofill.py` | Price list and FAQ drafted from pasted text, kept only where the text supports it |
| `joop/voice.py` | Voice messages: download from the channel, speech-to-text, then answered like text |
| `joop/audit.py`, `joop/web/audit.py` | The free chat audit: WhatsApp export parser, the numbers a prospect loses, the lead form |
| `joop/pitch.py` | Founder's demo on a prospect's own price list: autofill, slots, a scripted dialogue, a page to screenshot |
| `joop/free_plan.py` | Free plan for one master: eligibility, the Joop signature on first replies and bookings |
| `joop/trust.py` | AI self-disclosure at first contact; week-one dialogue review in the morning summary |
| `joop/upsell.py` | One add-on offered by code after a booking; "да" adds it |
| `joop/owner_commands.py` | /today, /week, /gaps, /help in the staff Telegram chat: the numbers by code |
| `joop/ig_comments.py` | Which Instagram comments get a Direct reply (questions, keywords); the client sends through the comment |
| `joop/gaps.py` | Empty slots for the week and the regulars to invite into them; the owner sends with one click |
| `joop/regulars.py` | The returning customer's last visits and upcoming booking, one line for the prompt |
| `joop/unfinished.py` | One follow-up with two free times to a customer who asked and went quiet |
| `joop/confirm.py` | "да" to the reminder confirms the visit; unconfirmed list for the morning summary; optional release |
| `joop/deposits.py` | Prepayment after an AI booking: details and deadline, receipts to staff, release when unpaid |
| `joop/broadcasts.py`, `joop/web/broadcasts.py` | Broadcasts to customer groups within channel rules, "стоп" to unsubscribe, batches in day hours |
| **Platform** | |
| `joop/web/app.py` | FastAPI app: the owner's panel and the channel webhooks |
| `joop/samples.py` | Which rows are still the sign-up example (fictional prices, staff, answers): flagged on the dashboard, not counted as done |
| `joop/web/saas.py`, `joop/billing.py`, `joop/partners.py` | Sign-up, test chat, billing (FreedomPay, transfers, cancel/resume), founder console, referrals |
| `joop/web/demo.py`, `joop/web/studio.py`, `joop/web/menu.py` | Live demo on the site, AI-drafted business sites, online menu with QR codes |
| `joop/altegio.py` | Altegio integration: prices, team and free times in, bookings out |
| `joop/crm.py` | amoCRM / Kommo: bookings, requests and orders sent as deals with contact and note |
| `joop/retention.py` | Retention at 30/90 days and first-week dialogues the owner checked, for the pilot page |
| `joop/stats.py` | Numbers for the dashboard, reports and the pilot; the panel test chat (`TEST_CHANNEL`) is left out of all of them, and of Altegio, amoCRM and staff reminders |
| **Operations** | |
| `joop/scheduler.py` | Reminders, summaries, weekly, monthly and day-7 reports, broadcast batches, prepayment deadlines, request reminders, amoCRM deals, Altegio sync, daily backup |
| `joop/founder_digest.py` | The founder's Monday line: the week in numbers, stored as a journal and sent to Telegram |
| `joop/health.py` | Alerts for the founder when model calls keep failing; `tell_founder` for other notes (a cancelled subscription) |
| `joop/recovery.py` | Answers the customers an outage left waiting, once the model works again |
| `joop/ops.py` | Pre-launch check (`python -m joop check`) and database backups |
| `deploy/setup.sh`, `docker-compose.yml`, `deploy/Caddyfile` | One-command server setup; the app plus Caddy for HTTPS |
| `joop/crypto.py`, `joop/security.py` | Channel tokens encrypted at rest; password hashing |
| `joop/migrations/` | Alembic migrations, run on start |
| **Quality** | |
| `tests/` | 425 tests with a frozen clock (`timeutil.clock`), with a fake model, fake channels and a fake Altegio API |
| `eval/` | Scripted dialogues on the real model; results on the `eval-results` branch |
