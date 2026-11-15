# Mobile app API

The Joop mobile app (Flutter, `mobile/`) talks to the server through `/api/mobile/...` (`joop/web/mobile.py`). It has
two sides: the business's owner and staff (sign-in, bookings) and customers (a business's card and its AI chat).

| Method and path | What it does |
| --- | --- |
| `POST /api/mobile/login` | `{"company", "password", "user"?}` → a token and who signed in (`owner`, `staff` or `master`) |
| `GET /api/mobile/me` | the business and the person behind the token |
| `GET /api/mobile/summary` | active bookings today, tomorrow and in 7 days, and the next visit |
| `GET /api/mobile/bookings?day=YYYY-MM-DD&days=N` | bookings of `N` days (1–31) from `day`, the business's local date |
| `POST /api/mobile/bookings/{id}/cancel` | cancels a booking and frees its time, the same code as the panel's button |
| `GET /api/mobile/orders` | open orders, newest first, then the last 30 closed; each with its next steps |
| `POST /api/mobile/orders/{id}/status` | `{"status"}`: the next step, the same code as the panel (stock back on cancel, the customer told) |
| `GET /api/mobile/leads` | new requests, then the last 30 done |
| `POST /api/mobile/leads/{id}/done` | marks a request done, with the person's name |
| `GET /api/mobile/customers/{key}` | the customer card (`customers.cards`, the panel's Клиенты): visits, `spend_som`, `rating`, `note`, `tags`, `upcoming`, the last 20 bookings and 10 orders; a master sees only her visits (`customers.for_staff`), 404 when the customer never came to her |
| `POST /api/mobile/customers/{key}` | `{note, tags}` → the card's note and tags (comma-separated, de-duplicated), the panel's code |
| `POST /api/mobile/bookings/{id}/pay` | `{amount, method, receipt?}` → what the customer paid after the visit (`cash`/`card`/`transfer`), the panel's Касса code (`cash.record`); amount 0 removes it; 409 for a cancelled booking, 422 for a wrong method or amount |
| `GET /api/mobile/cash?day=` | the day's takings `total`, `by_method`, `visits`, `unpaid` (visits that passed without a payment), `month` {`total`, `paid_visits`}; a master sees her own |
| `POST /api/mobile/services/{id}/available` | `{available}` → the stop list (the panel's «В продаже»): the AI stops offering the item and orders refuse it; masters 403; 409 when the item is sold out by the stock (back via «Склад») or the price list comes from Altegio |
| `GET /api/mobile/slots?day=` | free times of the day that staff can book a customer into (a master: only hers; the sign-up example's people left out) |
| `POST /api/mobile/bookings` | `{slot_id, name, phone?, service?}` → a booking made by staff (`source: "staff"`, `channel: ""`): takes the slot with `claim_slot` as the AI does, goes to Altegio when the salon uses it (then a phone is required); 409 when the time is taken, 422 for no name or a phone that is not a number. The AI's figures do not count it |
| `GET /api/mobile/conversations?q=` | the latest 100 real chats (the panel's Диалоги, test chats left out), newest first, with the last message, `ai_paused`, `blocked`; `q` finds by name (any case, Cyrillic too) or phone digits («0555 123» matches +996 555 123…) among the latest 1000; masters 403 |
| `GET /api/mobile/conversations/{id}` | a request's dialogue (last 50 messages), `ai_paused`, `ai_paused_until` (UTC), `takeover_minutes` (the pause the owner chose), `reply_blocked`; masters get 403 |
| `POST /api/mobile/conversations/{id}/reply` | `{text}` → staff reply through the customer's channel, same code as the panel: pauses the AI, closes the open requests; 422 with the reason when the channel no longer allows it (WhatsApp/Instagram 24 h) |
| `GET /api/mobile/services` | the price list |

Every call after sign-in sends `Authorization: Bearer <token>`.

- **Credentials** are the panel's: the company login (or the phone from sign-up) and its password, or a staff
  member's own login. Failed attempts share the panel's limit: 5 per address, then 15 minutes.
- **The token** is signed with `SESSION_SECRET` and is not stored. It lives 30 days and carries the last characters of
  the password hash, so a new password, or switching a staff login off, ends it at once.
- **Rights** follow the panel: a master's login sees and cancels only her own bookings and has no orders or requests
  (403). Settings, channels and payment stay in the panel.
- **Sections**: `login` and `me` return `sections` (`bookings`, `orders`, `leads`, `cash`) from the niche, so the app shows
  the tabs the panel's menu would: a cafe gets orders, a shop has no bookings.
- Test chats (the panel's and the owner's own test chats in real channels) are left out of bookings, orders and requests.

## Customers

A customer opens one business by its code, the slug in its `/c/<slug>` chat link or QR code, and the app remembers it.
There is no list of all businesses: a business joined Joop for its AI administrator, not for a public directory.

| Method and path | What it does |
| --- | --- |
| `GET /api/mobile/places/{slug}` | the public card: name, address, phone, hours, whether it books, the price list |
| `POST /c/{slug}/chat` | the web chat's own API: the same AI as in WhatsApp; `{"text", "visitor"}` → `{"reply"}` |
| `GET /c/{slug}/updates?visitor=…&after=…` | replies staff wrote from the panel to this customer |

The card shows only what the chat and price pages already show customers: the sign-up example's placeholder prices and
hours are left out, and a business whose chat is switched off is not found. The app keeps one random `visitor` token,
so a customer is the same web-chat visitor for every business; the web chat's limits per visitor, address and
business apply.

Tests: `tests/test_mobile.py`.

- **Customer key**: every booking carries `customer_key`, the card it belongs to (the phone's last nine digits, else the chat), empty when none.
- **Payments**: every booking in `/api/mobile/bookings` carries `suggested_som`, the price-list amount for an unpaid visit (exact service name, plus an accepted add-on), as the panel pre-fills it; 0 when unknown or already paid.
