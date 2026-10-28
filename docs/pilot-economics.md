# Pilot economics: cost of serving one dental clinic

Prices checked on 29 October 2026. Conversions use the National Bank of the Kyrgyz Republic rate
for 29 October 2026: 1 USD = 87.4486 KGS, 1 EUR = 97.2866 KGS (as republished by economist.kg).
Volumes are estimates for a small private clinic; replace them with real pilot numbers.

## Assumptions per clinic per month

- 150 customer conversations, about 6 AI replies each: about 1,000 AI replies.
- 100 appointment reminders.
- One prompt with a full price list and about 160 free slots is about 12,500 characters; with
  history this is an estimated 7,000 input tokens and 300 output tokens per reply.

## Monthly cost

| Item | Basis | Cost |
|---|---|---|
| Claude Haiku 5.5 | 1,000 replies × (7,000 input tokens at $0.10/MTok + 300 output at $0.50/MTok) | ≈ $0.85 ≈ 75 KGS |
| WhatsApp replies | Service messages inside the 24-hour window; the first 1,000 per number per month are free | 0 at this volume |
| WhatsApp reminders | 100 utility templates × $0.0077 (Kyrgyzstan is in Meta's "Other" market) | ≈ $0.77 ≈ 67 KGS |
| Instagram Direct | No per-message fee reported | 0 |
| Telegram | Bot API is free | 0 |
| Server | One 2 GB VPS shared by all clinics: DigitalOcean $12 or MyHost.kg 1,600 KGS | 1,049–1,600 KGS in total |

Result:

- First clinic, carrying the whole server: about 1,200–1,750 KGS per month.
- Each further clinic: about 150 KGS per month.
- At a price of 15,000 KGS (about $171.50), the direct costs are about 1–12% of revenue. The real
  cost is the founder's time: setting up the price list and slots, and support.

## Options not in the base setup

| Option | Price | Note |
|---|---|---|
| SMS reminders (local gateways) | 1.19–1.60 KGS per SMS | Sender name must be registered with operators; Nikita's public list dates from 2018, ask for a quote |
| Voice-note transcription, Groq whisper-large-v3-turbo | $0.04 per hour (10-second minimum per request) | Good for Russian; Kyrgyz error rates are high without fine-tuning |
| Voice-note transcription, OpenAI gpt-transcribe | $0.0045 per minute | No published Kyrgyz benchmark; WhatsApp OGG audio must be converted first |
| Unofficial WhatsApp connection (Green-API) | 690 RUB per month per number | Number can be banned; not recommended for a medical business |
| Official WhatsApp through a provider (360dialog) | €49 / $59 per month per number plus Meta fees | Only if connecting directly to Meta is not possible |

## Policy notes

- Since 15 January 2026, Meta allows AI bots on the WhatsApp Business Platform only when they
  serve a specific business purpose (bookings, support). A booking assistant fits; a general chat
  assistant does not. Keep the "do not discuss unrelated topics" rule in the prompt.
- From 1 October 2026, utility templates sent inside the 24-hour window are also billable, and the
  free allowance is 1,000 service messages per number per month.

## Sources

- Claude Haiku 5.5 pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Meta WhatsApp pricing and markets: https://developers.facebook.com/docs/whatsapp/pricing ;
  rates effective 1 Oct 2026: https://whautomate.com/whatsapp-business-api-pricing ,
  https://chatmaxima.com/blog/whatsapp-service-message-pricing-october-2026/ ;
  October 2026 rule changes: https://www.ycloud.com/ru/blog/whatsapp-api-message-pricing-update-effective-october-1-2026
- WhatsApp AI chatbot policy: https://respond.io/blog/whatsapp-chatbot-policy-2026
- Instagram messaging fees: https://zernio.com/blog/instagram-messaging-api (third-party)
- Servers: https://digitalocean.com/pricing/droplets , https://www.myhost.kg/en/
- SMS: https://smspro.kz/kz/prices.html (Nikita list, 2018), https://devino.kg/
- Speech-to-text: https://console.groq.com/docs/speech-to-text ,
  https://developers.openai.com/api/docs/models/gpt-transcribe.md ,
  Kyrgyz benchmarks: https://huggingface.co/BuzzASR/kyrgyz , https://arxiv.org/pdf/2607.10371
- WhatsApp providers: https://green-api.com/tariffs-policy-green-api.pdf ,
  https://docs.360dialog.com/docs/pricing
- Exchange rate: https://economist.kg/dengi/2026/10/28/kursy-valyut-2026-10-29/
