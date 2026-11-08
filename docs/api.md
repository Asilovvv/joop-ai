# Joop API and webhooks

Both are off until the business owner turns them on in the panel: «API и вебхуки» (owner login only).
Code: `joop/api.py`, routes in `joop/web/api.py`.

## REST API (read-only)

```
GET /api/v1/bookings | /api/v1/orders | /api/v1/leads | /api/v1/customers
Authorization: Bearer joop_...
```

- One key per business. It is shown once; Joop stores only its SHA-256. A new key replaces the old one at once.
- 200 rows per call, oldest first. `has_more: true` means ask again with `?after_id=<last id>`
  (customers: `?offset=200`). `?since=2026-11-01T00:00:00Z` returns rows created from that moment (an offset such as `+06:00` is honoured).
- Times: `created_at` and `paid.at` are UTC with `Z`; `start_local` is the business's local time.
- The test chat («Проверить ИИ») is never included. Leads are customer requests only (`request`, `lead`, `handoff`).
- Order `status`: `new`, `accepted`, `sent` (delivery: on the way; pickup: ready to collect), `done`, `cancelled`.
- 120 calls a minute per key, then `429` with `Retry-After: 60`. Wrong or missing key: `401`.

## Webhooks

`POST` to the owner's https address with JSON:

```json
{"event": "booking.created", "business": "<slug>", "sent_at": "2026-11-04T17:14:00Z", "data": { ... same as the API row ... }}
```

Events: `booking.created`, `booking.paid` (staff recorded a payment in «Касса»), `order.created`, `lead.created`;
`test` from the panel's «Отправить тест».

Headers: `X-Joop-Event`, `X-Joop-Signature: sha256=<hex HMAC-SHA256 of the raw body with the secret>`.
Check it on the receiving side, e.g. in Python:

```python
hmac.compare_digest(request.headers["X-Joop-Signature"], "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest())
```

Delivery: the scheduler sends up to 30 events a tick (at most 15 seconds per business), in the order things happened.
A non-2xx answer stops the round; it is retried on the next tick, for up to 24 hours from the first attempt, then given
up (the panel shows how many; the API still has the data). Redirects are not followed; timeouts are 3 s to connect,
5 s per read. Only events from the moment the address was saved, at most 3 days back, are sent.

Safety: the address must be https on port 443 or 8443, in Latin letters (punycode for IDN), without login/password,
and every address its host resolves to must be public. This is checked when it is saved and again before each send,
and the request goes to the very address that was checked (SNI and Host keep the name, so TLS still verifies it), so
the webhook cannot reach Joop's internal network.
