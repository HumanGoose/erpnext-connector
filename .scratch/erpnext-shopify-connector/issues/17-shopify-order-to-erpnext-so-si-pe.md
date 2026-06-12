# Shopify Order → ERPNext Sales Order + Sales Invoice + Payment Entry

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 22, 23, 24, and the inbound-dedup half of 27.

## What to build

Implement `canonicalize("order", ...)` tracking a Shopify Order's line items (variant references, quantities, prices), taxes, shipping charges, discounts, and totals, plus its Fingerprint.

Wire a webhook receiver for the Shopify `orders/create` topic (HMAC-verified). The sync handler:

- Performs idempotency/dedup: if a Synced Entity for the incoming `shopify_order_gid` already exists (e.g. webhook redelivery), no new ERPNext document-creation calls are made — per story 27, a Shopify order should never produce more than one ERPNext document set.
- On a genuine new order, creates — together — an ERPNext Sales Order, Sales Invoice, and Payment Entry, reflecting that Shopify orders are pre-paid at the point of creation.
- Maps line items to ERPNext variant Items via the variant Synced Entities from issue 05.
- Resolves the order's customer via the customer Synced Entity from issue 15, creating the ERPNext Customer inline (reusing issue 15's logic) if the customer hasn't synced yet.
- Carries totals (taxes, shipping, discounts) onto the Sales Invoice so financial totals reconcile between systems. Per the PRD's Out of Scope note, exact Sales Taxes and Charges *template* fidelity is not required for this issue — resulting totals must match, with tax-line-template fidelity tracked as a separate follow-up.
- Stores `shopify_order_gid` on the Sales Order and Sales Invoice, and creates Synced Entity rows for the order group (Sales Order, Sales Invoice, Payment Entry, sharing a group key) with both Fingerprints populated.

## Acceptance criteria

- [x] `canonicalize("order", ...)` tracks line items (variant ref, qty, price), taxes, shipping, discounts, and totals; Fingerprint is stable under untracked-field changes.
- [x] Webhook receiver routes Shopify `orders/create` (HMAC-verified) to the sync handler.
- [x] If a Synced Entity for the incoming `shopify_order_gid` already exists, the handler makes no new `ERPNextClient` document-creation calls.
- [x] On a genuine new order, the handler creates an ERPNext Sales Order, Sales Invoice, and Payment Entry, with line items referencing the correct ERPNext variant Items (via Synced Entities from issue 05) and quantities/prices matching the Shopify order.
- [x] Sales Invoice totals (including tax, shipping, and discount amounts) match the Shopify order's totals.
- [x] If the order's customer has no existing Synced Entity, the handler creates the ERPNext Customer inline (reusing the customer canonicalize/sync logic from issue 15) before creating the order documents.
- [x] `shopify_order_gid` is stored on the created Sales Order and Sales Invoice; Synced Entity rows are created for the order group sharing a group key, with both Fingerprints populated.

## Blocked by

- 05-shopify-product-to-erpnext-item.md
- 15-shopify-customer-to-erpnext-customer.md

## Comments

- Implemented: `connector/sync/orders.py::handle_shopify_order_create` (plus `_erpnext_line_items`, `_resolve_customer`, `_tax_rows`, `_save_order_group`), `connector/fingerprint.py::_canonicalize_order`. Wired as `POST /webhooks/shopify/orders` (`orders/create` topic, HMAC-verified) in `connector/api/shopify_webhooks.py`. Tests in `tests/sync/test_orders.py`: new order creates SO+SI+PE with resolved/inline-created customer (3 tests covering the new-order, redelivery-idempotency, and guest-customer paths), plus HTTP routing in `tests/api/test_shopify_sync_webhooks.py`. `pytest -q` passes (99 passed total).
