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
| `GET /api/mobile/services` | the price list |

Every call after sign-in sends `Authorization: Bearer <token>`.

- **Credentials** are the panel's: the company login (or the phone from sign-up) and its password, or a staff
  member's own login. Failed attempts share the panel's limit: 5 per address, then 15 minutes.
- **The token** is signed with `SESSION_SECRET` and is not stored. It lives 30 days and carries the last characters of
  the password hash, so a new password, or switching a staff login off, ends it at once.
- **Rights** follow the panel: a master's login sees and cancels only her own bookings and has no orders or requests
  (403). Settings, channels and payment stay in the panel.
- **Sections**: `login` and `me` return `sections` (`bookings`, `orders`, `leads`) from the niche, so the app shows
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
