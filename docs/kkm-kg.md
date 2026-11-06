# Fiscal receipts (ККМ) in Kyrgyzstan and Joop

Research, 6 Nov 2026. Secondary sources; check the Tax Code and the Cabinet's exemption list before advising a client.

## What the law asks

- Tax Code art. 128: settlements with individuals for goods, works and services go through a cash register (ККМ)
  from the State Tax Service registry, with a paper or electronic receipt — under any tax regime (patent and single
  tax included), except activities on the Cabinet of Ministers' exemption list. Fiscal software integrated with the
  tax service's system counts as a ККМ. (quietbuh.com summary of the Code as amended 6 Aug 2026.)
- A draft Cabinet resolution (public discussion from 22 Jun 2026) removes the exemption for purely cashless
  settlements, requires itemized receipts from 1 Apr 2027, and keeps the rule that a товарный чек does not replace a
  fiscal one. Not in force when this was written. (knews.kg)
- The Cabinet moved some ККМ requirements to 1 Jul 2027 (tazabek.kg, 8 Oct 2026; details behind a paywall).
- QR and transfer payments are under tax control; taking business payments to a personal QR or card is a violation.

## What this means for Joop

- Joop is not a ККМ and does not print fiscal receipts. Becoming one means the registry, a technical service centre
  (ЦТО) contract and certification — a separate regulated product, not a feature.
- Operators already sell software ККМ with an integration API, e.g. ofd1.kg (Neo Fiscal Driver, 300–500 som a month
  per register; API on request, after testing and an interaction agreement). That is the realistic path if pilots
  ask for receipts from the chat: Joop sends the paid visit to the business's own operator account.
- Now: «Касса» keeps a «чек ККМ пробит» mark per payment (Booking.receipt_at) and counts payments without it, so the
  master does not forget the receipt. The page says plainly that it is the owner's count, not a tax document.

## Sources

- https://quietbuh.com/blog/esf-i-kkm-kyrgyzstan-kto-obyazan
- https://knews.kg/2026/06/22/kabmin-kyrgyzstana-nameren-uzhestochit-pravila-primeneniya-kkm-novye-trebovaniya-i-otsrochki/
- https://www.tazabek.kg/news:2546917
- https://iakupbaeva.com/posts/mnephn95f1-qr-oplata-i-beznalichnie-instrumenti-obe
- https://ofd1.kg/
