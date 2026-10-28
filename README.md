# Joop AI

AI customer-service operator for small businesses in Kyrgyzstan.
It answers customers in Telegram in **Kyrgyz and Russian**, using only the
business's own price list and FAQ, collects booking requests, notifies the
owner instantly, and hands difficult conversations to a human.

*Joop (жооп) means "answer" in Kyrgyz.*

## Features

- Answers grounded in a per-business YAML profile (services, prices, hours, FAQ); does not invent facts
- Replies in the customer's language (Kyrgyz / Russian)
- Lead capture via LLM tool use: name, phone (validated), service, preferred time
- Instant owner notification in Telegram for every lead
- Human handoff: bot stops auto-replying, forwards messages to the owner; owner answers with `/reply` and returns the bot with `/resume`
- Owner commands: `/leads`, `/export` (CSV for Excel), `/stats`
- Prompt-injection guard in the system prompt
- Scripted evaluation set (`eval/`) with pass/fail metrics and latency for the thesis
- 30 unit tests with a fake LLM (no network needed); 24 scripted evaluation cases in Kyrgyz, Russian and mixed language (24/24 passed with claude-haiku-5-5, Oct 2026)

## Architecture

```
Telegram ──► aiogram router (joop/bot.py)
                 │  handoff? ── yes ──► forward to owner
                 ▼ no
             Agent (joop/agent.py) ──► Claude API (tool use)
                 │      tools: save_lead, handoff_to_human
                 ▼
             Storage (joop/storage.py, SQLite): messages, leads, chats
                 │
                 └──► owner notification (Telegram)
Business profile (business.yaml) ──► system prompt
```

## Quick start

1. Python 3.10+:
   ```bash
   pip install -r requirements.txt
   ```
2. Create a bot with [@BotFather](https://t.me/BotFather) and copy its token.
3. Get an Anthropic API key at https://console.anthropic.com.
4. Configure (interactive, secrets are typed hidden and saved to `.env`):
   ```bash
   python -m joop.setup
   ```
   It also creates `business.yaml` from the demo profile; replace it with the real business data.
5. Run:
   ```bash
   python -m joop
   ```
6. In Telegram, send `/myid` to the bot, put the number into `OWNER_CHAT_ID` in `.env`, restart.
   From now on, leads and handoffs arrive in that chat.

Try it in the terminal without Telegram:
```bash
python -m joop.cli business.example.yaml
```

## Owner commands

| Command | What it does |
|---|---|
| `/leads` | Last 20 leads |
| `/export` | All leads as `leads.csv` |
| `/stats` | Chats, messages, leads, open handoffs |
| `/reply <chat_id> <text>` | Answer a customer as a human |
| `/resume <chat_id>` | Let the bot reply in that chat again |
| `/myid` | Show your chat id (works for anyone) |

## Onboarding a new client

1. Copy `business.example.yaml` to `clients/<name>.yaml`, fill in the real data.
2. Create a separate bot token for the client.
3. Run one process per client with its own `.env` (`BUSINESS_FILE`, `DB_PATH`, token).

## Tests and evaluation

```bash
python -m pytest -q                       # unit tests, no network
python -m eval.run_eval                   # real model, needs ANTHROPIC_API_KEY
```
`eval/run_eval.py` writes `eval/results.json` (pass/fail per case, lead and
handoff detection, average latency). Have a native speaker review the Kyrgyz cases.

## Deploy (24/7 server)

See [DEPLOY.md](DEPLOY.md): one-command installer for Ubuntu (systemd service,
auto-restart, daily database backup), a Docker alternative, and verified
hosting options including a provider that accepts Kyrgyz payment methods.

## Demo profiles

| File | Business | Evaluation set |
|---|---|---|
| `business.example.yaml` | Beauty studio | `eval/cases.yaml` (24 cases) |
| `business.dental.example.yaml` | Dental clinic, with medical-safety rules (no diagnosis, no medication advice, urgent symptoms escalated) | `eval/cases_dental.yaml` (14 cases) |

`/stats` in Telegram shows token usage and API cost; the evaluation reports
average cost per conversation (`joop/pricing.py` holds the published prices).

## Roadmap

- WhatsApp Business API channel
- Voice messages (speech-to-text for Kyrgyz)
- Web dashboard for owners, Google Sheets / CRM sync
- Multi-tenant mode (many businesses in one process)

## Security

Never commit `.env`. The bot does not ask customers for card numbers,
passwords or ID documents.
