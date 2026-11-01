# Joop AI in the Altegio Marketplace: listing package

Status (1 November 2026): the integration works through Altegio's public Online Booking API with a partner
token (`joop/altegio.py`). Publishing in the Altegio Marketplace needs a developer account and three more
pieces on Joop's side, listed below. Nothing here has been sent to Altegio yet.

## 1. What already works

- A salon enters its Altegio location ID in the panel ("Каналы" → Altegio). Every 10 minutes Joop copies the
  price list, the team and free times for the next 7 days, so the AI answers from the salon's real schedule.
- When the AI books, Joop's own checks run first, then Altegio checks the time again (`book_check`) and creates
  the record (`book_record`). A time Altegio reports as taken is closed in Joop and the customer gets other
  times. If Altegio does not answer, the booking becomes a request that staff confirm.
- A visit cancelled in Altegio is released in Joop at the next sync.
- Tested against a fake Altegio API (`tests/test_altegio.py`); not yet run against a real location.

Endpoints used: `book_services`, `book_staff`, `book_dates`, `book_times`, `book_check`, `book_record`
(base `https://api.alteg.io/api/v1`, header `Accept: application/vnd.api.v2+json`, 200 requests a minute).

## 2. What the Marketplace asks for

From Altegio's guide "Step-by-step guide to placement in the marketplace" (knowledge base article
6745848593181):

1. A developer account and an app created in the developer personal account.
2. Integration with the Marketplace API: a connection request that links the app to the salon's location,
   sending payment data to Altegio, and a webhook for when the salon disconnects the app in Altegio.
3. A test on your own location before moderation (the "link to request a review", then "Connect", then a
   connection request from your service within an hour).
4. Moderation: the reviewers check the connection, payment and chargeback data, disconnecting and
   reconnecting, and connecting a salon that already exists in your system.

Partnership contact named in Altegio's guides: partner@alteg.io.

## 3. What Joop still needs to build (after the developer account exists)

The exact endpoints are in the Marketplace API documentation, which opens inside the developer account, so
they are not guessed here.

| Piece | Joop side |
|---|---|
| Connection | A page that receives the salon from Altegio's "Connect" button, finds or creates the Joop company and stores the location ID; then the connection request to Altegio |
| Payment data | When a salon pays for Joop (FreedomPay or transfer, `joop/billing.py`), send the payment to Altegio; the same for refunds |
| Disconnection | A webhook that stops the sync and bookings for that location and tells the owner in Telegram |
| Existing user | If the salon already has a Joop company, attach the location to it instead of creating a second one |

## 4. What the owner does

1. Register an Altegio developer account and create the app "Joop AI".
2. Get a test location (your own salon account or a partner salon) for step 2.5 of the guide.
3. Pass the Marketplace API documentation link to development; the pieces in section 3 are built and tested
   against it.
4. Fill in the listing (section 5), screenshots and prices, then send it to moderation.

## 5. Listing texts

**Name:** Joop AI — ИИ-администратор в Telegram, WhatsApp и Instagram

**Short description (RU):** ИИ-администратор отвечает клиентам салона в Telegram, WhatsApp, Instagram и в
чате на сайте за секунды, по-кыргызски и по-русски, и записывает их прямо в ваш Altegio.

**Short description (EN):** An AI receptionist that answers your salon's customers in Telegram, WhatsApp,
Instagram and website chat within seconds, in Kyrgyz and Russian, and books them straight into Altegio.

Replies to guests in English and other languages are on pull request #59; add them to the texts after its
evaluation on the real model.

**Full description (RU):**

Клиенты пишут ночью, в выходные и когда администратор занят. Joop AI отвечает сразу: цены и услуги берёт из
вашего Altegio, предлагает только свободное время и создаёт запись в Altegio, когда клиент согласен.

- Цены, мастера и свободные окна — из Altegio, обновляются каждые 10 минут.
- Перед записью время проверяется в Altegio ещё раз: двойной записи не будет.
- Отвечает по-кыргызски и по-русски.
- Если ИИ не знает ответа или клиент недоволен, вопрос сразу уходит администратору в Telegram.
- Напоминания о визите, оценка после визита, приглашение прийти снова, рассылки по группам клиентов,
  предоплата за запись.
- Утренняя сводка и отчёт за месяц: сколько клиентов ответил и записал ИИ, сколько — в нерабочее время.

**Full description (EN):**

Customers write at night, at weekends and while the receptionist is busy. Joop AI answers at once: it takes
prices and services from your Altegio, offers only free times and creates the record in Altegio once the
customer agrees. Times are checked in Altegio again right before booking, so a time is never booked twice.
It answers in Kyrgyz and Russian, hands anything it cannot answer
to staff in Telegram, and sends reminders, rating requests, broadcasts and a monthly report.

**Category (to choose in the form):** messengers / online booking assistants, whichever the form offers.

**Price:** to be set by the owner; nothing is published yet (`PRICE_SOM` is empty).

**Screenshots:** the panel's dashboard, a Telegram dialogue with a booking, the "Каналы" page with Altegio
connected, the bookings page. Use the demo company, never real customers.

**Support:** the owner's contact e-mail and Telegram (`CONTACT_EMAIL`, `CONTACT_TELEGRAM`).
