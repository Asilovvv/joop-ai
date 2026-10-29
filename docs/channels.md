# Connecting channels

Checked against Meta's developer documentation on 29 October 2026. Meta renames dashboard menus
often; if a label below does not match, search the dashboard for the setting's name.

## What each channel needs before real customers can use it

| | Telegram | WhatsApp, new number owned by the business | WhatsApp, the business's existing WhatsApp Business app number | Instagram Direct |
|---|---|---|---|---|
| Works today | Yes | Yes | No | Only as a sandbox |
| What it takes | A bot token from @BotFather | The business's own Meta app and WhatsApp account; payment method | Onboarding through a Meta Tech Provider or Solution Partner ("coexistence") | App Review and Business Verification, app in Live mode |
| Time | Minutes | About a day | 2–5 weeks for our own Tech Provider approval | 2–5 weeks |
| Reminders the day before | Yes | Yes, with an approved template | Yes, with an approved template | Only within 24 h of the customer's last message |

Key rules behind this table:

- **Instagram.** Without App Review, the API only exchanges messages with people who have a role
  on the app (developers, testers). That is enough to demo the bot on a clinic's real account, but
  patients who write in will not reach it. Serving real customers needs Advanced Access, which
  requires App Review for `instagram_business_basic` and `instagram_business_manage_messages` plus
  Business Verification. An app owned by the clinic's own verified business might work with
  Standard Access in Live mode; Meta's pages contradict each other on this, so test it with one
  account before promising it.
- **Instagram reminders.** An app can message a user only within 24 hours of their last message.
  The HUMAN_AGENT tag (7 days) is for messages typed by a person, not automated ones. Joop AI
  therefore sends Instagram reminders only inside the window and otherwise puts the booking on the
  staff's "remind manually" list.
- **WhatsApp coexistence** (keeping the clinic's WhatsApp Business app on the same number) is
  officially supported, but only through Embedded Signup run by a Tech Provider or Solution
  Partner. Becoming a Tech Provider requires Business Verification and App Review with Advanced
  Access. Until then, a pilot can use a separate new number.
- **WhatsApp limits for a new business portfolio**: messages outside the 24-hour window can reach
  250 different people per 24 hours; replies inside the window do not count. Business Verification
  raises the limit.
- **Payment**: Meta charges service messages after the first 1,000 per number per month and all
  template messages. Add a payment method in WhatsApp Manager, or Meta stops delivering service
  messages once they become charged.

Start Business Verification for your company now; it can take up to 14 business days and both
WhatsApp coexistence and Instagram depend on it.

## Telegram

1. In Telegram, open @BotFather, send `/newbot`, copy the token.
2. Panel → "Каналы" → paste the token → save.
3. On a server: press "Подключить Telegram" (needs `PUBLIC_BASE_URL` with https).
   On a laptop: run `python -m joop dev --slug <login>` instead; it polls Telegram.
4. Panel → "Настройки": send the shown `/admin <code>` to the bot from the chat that should receive
   booking notifications (a private chat or a staff group with the bot added).

## Webhook settings shared by WhatsApp and Instagram

Set these in `.env` on the server, then restart:

- `META_VERIFY_TOKEN`: any random string; you type the same value into Meta's webhook form.
- `META_APP_SECRET`: the app secret from the Meta app's basic settings. Joop AI rejects webhooks whose
  `X-Hub-Signature-256` does not match it.
- `INSTAGRAM_APP_SECRET`: only if the Instagram product shows its own app secret.

Callback URL for both products: `https://<your domain>/webhooks/meta`.

## WhatsApp Cloud API (business-owned app, new number)

1. At https://developers.facebook.com create an app with the WhatsApp use case, inside the
   clinic's business portfolio. Business Verification is not needed to start.
2. In the WhatsApp section, add and verify a phone number that is not used in a WhatsApp app.
   Copy its **Phone number ID**.
3. In the business portfolio settings, create a system user, give it the app and the WhatsApp
   account, and generate a token with `whatsapp_business_messaging` and
   `whatsapp_business_management`. A system-user token does not expire like a temporary test token.
4. Add a payment method in WhatsApp Manager.
5. In the app's WhatsApp webhook configuration, enter the callback URL and verify token and
   subscribe to the `messages` field. With coexistence, also subscribe to `smb_message_echoes`.
6. Panel → "Каналы": Phone number ID and the token.
7. Reminder template: in WhatsApp Manager create a template named `appointment_reminder`,
   category Utility, language Russian, with three variables in the body, for example:

   > Здравствуйте, {{1}}! Напоминаем о записи {{2}}, специалист: {{3}}. Если планы изменились, ответьте на это сообщение.

   Joop AI fills in the customer's name, the date and time, and the specialist. After approval, put
   the template name into the panel. Keep marketing content out of it, or Meta will recategorise it
   as marketing (about 8 times the price).

## Instagram Direct (Instagram API with Instagram Login)

No Facebook Page is needed with this setup.

1. The clinic's Instagram account must be a public professional (Business or Creator) account.
2. In the Meta app, add the Instagram product and open the Instagram Login API setup.
3. Add the clinic's account and generate an access token; the clinic logs in to approve.
   The token lives 60 days. Joop AI refreshes it weekly, so paste it once.
4. Copy the account's Instagram ID: it is the `entry.id` that Meta puts in every webhook, and
   Joop AI uses it to find the business.
5. Subscribe the webhook fields `messages` and `message_echoes`. Echoes let Joop AI notice when
   staff answer from the Instagram app and pause the AI in that conversation for 12 hours.
6. Panel → "Каналы": Instagram account ID and token.
7. To serve real patients, request Advanced Access through App Review and complete Business
   Verification, then switch the app to Live.

## Sources

- WhatsApp pricing and markets: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing
- WhatsApp messaging limits: https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits
- Coexistence: https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users
- Echo webhook: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/smb_message_echoes
- Tech Provider requirements: https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers
- Business-scoped user IDs: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-scoped-user-ids
- Graph API versions (v26.0 current): https://developers.facebook.com/docs/graph-api/changelog/versions
- Instagram access levels and App Review: https://developers.facebook.com/documentation/instagram-platform/app-review
- Instagram messaging and the 24-hour window: https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api
- HUMAN_AGENT rules: https://developers.facebook.com/docs/messenger-platform/reference/send-api
- Instagram webhooks: https://developers.facebook.com/documentation/instagram-platform/webhooks/setup
- Instagram tokens: https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login
