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
  (customers: `?offset=200`). `?since=2026-11-01T00:00:00Z` returns rows created from that UTC moment.
- Times: `created_at` and `paid.at` are UTC with `Z`; `start_local` is the business's local time.
- The test chat («Проверить ИИ») is never included. Leads are customer requests only (`request`, `lead`, `handoff`).
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

Delivery: the scheduler sends up to 30 events a tick, in order. A non-2xx answer stops the round and is retried on
the next tick, up to 5 attempts per event. Redirects are not followed. Only events from the moment the address was
saved, at most 3 days back, are sent.

Safety: the address must be https, without login/password, and every address its host resolves to must be public.
This is checked when it is saved and again before each send, so the webhook cannot reach Joop's internal network.
