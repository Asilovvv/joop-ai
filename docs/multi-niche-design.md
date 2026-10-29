# Multi-niche design (proposal, not implemented)

Status: approved 29 Oct 2026 (all niches, start now). Implemented in the same week, with these
differences from the proposal below:

- Tables were extended instead of renamed: `Service` is the catalog (plus `available`, `price_value`,
  `category`), `Staff` is the resource (plus `capacity`).
- Packs live in `joop/niches/<name>/` (pack.yaml, demo.yaml, cases.yaml) for dental, beauty, restaurant,
  realty, auto, education, wholesale and a generic `other`.
- Minimum order, delivery fee and the free-delivery threshold are business settings checked in code.
- Large catalogs: instead of a model tool, a keyword match picks up to 40 items relevant to the last
  customer messages once a catalog exceeds 80 available items; the prompt also lists the categories.
- Alembic migrations (`joop/migrations`, baseline `0001`) run at startup; `python -m joop make-migration`
  generates new ones and a test fails if models and migrations differ.
- Not built: per-pack JSON schemas for catalog attributes (attributes are free text in the item name and note).

## 1. What changes in the data model

Today the model is shaped around a clinic: `Service` (price list), `Staff`, `Slot`, `Booking`,
`Lead`. The proposal generalises three of them and adds one.

| Today | Proposed | Why |
|---|---|---|
| `Service` | `CatalogItem`: kind, category, name, name_ky, price, unit, `attrs` (JSON checked against the pack's schema), available, sort | The same table holds a price list, a menu, property listings, courses or goods |
| `Staff` | `Resource`: kind (specialist, table, bay, agent, group), name, capacity, handles, active | Slots belong to whatever is booked: a doctor, a table for 4, a car bay |
| `Slot` | unchanged, `staff_id` becomes `resource_id` | |
| `Booking` | + `party_size`, + `item_id` (e.g. the property shown), + `attrs` | Table for 6 guests; viewing of flat #12 |
| `Lead` | + `attrs` (qualification answers: budget, district, rooms) | Real estate and wholesale leads |
| — | **`Order`** + **`OrderLine`**: items, quantity, modifiers, total computed by code, pickup or delivery, address, time, status | Cafe and restaurant orders, wholesale orders |

## 2. Outcomes: what a conversation can produce

The model's JSON answer is built from the outcomes the pack enables. Code validates every outcome
before anything is saved; the model only proposes.

| Outcome | Fields the model proposes | What the code checks |
|---|---|---|
| booking | slot, name, phone, item, party size | slot free and in the future, claimed atomically; party size ≤ resource capacity |
| request | name, phone, item, preferred time | name and phone present, phone valid |
| order | lines (item, quantity, modifiers), pickup or delivery, address, time, name, phone | every item exists and is available (not on the stop list), quantity 1–50, **total recomputed from catalog prices**, minimum order and delivery area from settings |
| lead | qualification fields from the pack | required fields present |
| handoff | short reason | — |

The customer always gets the code's version: if the model said "800 сом" and the catalog total is
950, the reply is corrected before sending.

## 3. A niche pack

```
niches/restaurant/
  pack.yaml          # label, outcomes, resource kinds, catalog schema, questions, rules, templates
  demo.yaml          # demo profile: menu, tables, FAQ (fictional, marked as demo)
  cases.yaml         # evaluation dialogues, at least 12, 4 in Kyrgyz
```

Example `pack.yaml` for a restaurant:

```yaml
name: restaurant
label_ru: Кафе и рестораны
outcomes: [booking, order, handoff]
resources: [{kind: table, label_ru: Стол, capacity: true}]
catalog:
  kind: menu_item
  attrs:                       # JSON schema for CatalogItem.attrs
    weight_g: {type: integer}
    spicy: {type: boolean}
    modifiers: {type: array, items: {type: string}}
booking:
  ask: [date, time, party_size, name, phone]
order:
  modes: [pickup, delivery]
  ask: [lines, mode, address_if_delivery, time, name, phone]
rules_ru:
  - Не обещай блюда со стоп-листа.
  - Состав и аллергены называй только из карточки блюда; если их нет — передай вопрос администратору.
reminders: [booking]
panel: [orders, tables, menu, conversations, leads]
```

The dental pack keeps today's behaviour: outcomes `[booking, request, handoff]`, resources
`specialist`, medical rules.

## 4. Large catalogs

A menu of 120 dishes or 300 listings does not fit well in every prompt: cost grows and accuracy
drops. Rule: up to about 80 items the catalog goes into the prompt as today; above that the model
gets a `search_catalog` tool (filter by category, price, attributes; returns at most 10 items) and
a short category list in the prompt.

## 5. Migration of existing data

There are no production deployments yet, but the dental pilot will start before this work ends.

1. Add Alembic migrations first, as a separate step with no model changes.
2. One migration renames `service` to `catalog_item` and `staff` to `resource`, adds the new
   columns with defaults, and sets `kind` = `service` / `specialist` for existing rows.
3. The full test suite and both evaluation sets must pass unchanged after the migration.
4. Backup of the database before running it on any live server.

## 6. Order of work and rough size

| Step | Content | Estimate |
|---|---|---|
| 0 | Alembic; pack loader; dental and beauty as packs, no behaviour change | 3 days |
| 1 | Restaurant: table booking (capacity) | 2 days |
| 2 | Restaurant: menu, stop list, orders with code-computed totals, order notifications | 4 days |
| 3 | Real estate: listings with attributes, qualification lead, viewing as a booking | 3 days |
| 4 | Large catalogs: `search_catalog` tool | 2 days |
| 5 | Auto service, training centre, wholesale | 1–2 days each |

Each step: its own branch and PR, tests, an evaluation run with the real model, and a short report
(passed, cost per conversation, reply time).

## 7. Main risks

1. **Focus.** The diploma is due 1 December and the dental pilot is not running yet. Steps 0–2 take
   about two weeks. Recommendation: freeze the diploma scope on the current platform and do this
   work only after the first paying clinic.
2. **Orders without integrations.** Restaurants run POS systems (iiko, Poster and others) and
   delivery services. Without integration, the stop list and order intake are manual in the panel,
   and staff re-enter orders. Integration is a separate project per system and is not planned here.
3. **Payments.** Taking prepayment for orders or deposits needs a payment provider and a contract;
   out of scope. The AI states the business's own payment rules from its profile.

## 8. Decisions needed from the owner

1. Approve the data model and the pack structure (sections 1–3).
2. Which niche goes second after dental: beauty (closest, cheapest) or restaurants (bigger market,
   more work).
3. Restaurants at the start: table booking only, or orders too; pickup only, or delivery too.
4. When to start: now, or after the first paying clinic (recommended).
