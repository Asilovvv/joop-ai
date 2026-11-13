# Mobile app API

The Joop mobile app (Flutter) talks to the server through `/api/mobile/...` (`joop/web/mobile.py`). It is for the
business's owner and staff; customers keep writing in Telegram, WhatsApp, Instagram and the web chat.

| Method and path | What it does |
| --- | --- |
| `POST /api/mobile/login` | `{"company", "password", "user"?}` → a token and who signed in (`owner`, `staff` or `master`) |
| `GET /api/mobile/me` | the business and the person behind the token |
| `GET /api/mobile/summary` | active bookings today, tomorrow and in 7 days, and the next visit |
| `GET /api/mobile/bookings?day=YYYY-MM-DD&days=N` | bookings of `N` days (1–31) from `day`, the business's local date |
| `POST /api/mobile/bookings/{id}/cancel` | cancels a booking and frees its time, the same code as the panel's button |
| `GET /api/mobile/services` | the price list |

Every call after sign-in sends `Authorization: Bearer <token>`.

- **Credentials** are the panel's: the company login (or the phone from sign-up) and its password, or a staff
  member's own login. Failed attempts share the panel's limit: 5 per address, then 15 minutes.
- **The token** is signed with `SESSION_SECRET` and is not stored. It lives 30 days and carries the last characters of
  the password hash, so a new password, or switching a staff login off, ends it at once.
- **Rights** follow the panel: a master's login sees and cancels only her own bookings. Settings, channels and
  payment stay in the panel.
- The panel's test chat (`console`) is left out of bookings and counts.

Tests: `tests/test_mobile.py`.
