# ERPNext Delivery Note → Shopify Fulfillment (full/partial)

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 28, 30.

## What to build

Implement `canonicalize("fulfillment", ...)` tracking which line items/quantities of an Order have been fulfilled, plus its Fingerprint.

A Frappe Webhook fires on Delivery Note submission for an Order's items. The sync handler:

- Resolves the Delivery Note's Sales Order to its order Synced Entity (and `shopify_order_gid`).
- Performs Echo detection against `erpnext_fingerprint` for the `fulfillment` Synced Entity.
- On a genuine new fulfillment, calls Shopify's `fulfillmentCreate` for the corresponding line items/quantities, matched via the variant Synced Entities from issue 05 — supporting partial fulfillment (a subset of the Order's items/quantities).
- Records/updates the `fulfillment` Synced Entity with `shopify_fulfillment_gid` and both Fingerprints, and stores `shopify_fulfillment_gid` on the Delivery Note's Custom Field.

## Acceptance criteria

- [x] `canonicalize("fulfillment", ...)` tracks fulfilled line items and quantities for an Order; Fingerprint reflects which items/quantities have been fulfilled.
- [x] Webhook receiver routes ERPNext Delivery Note submission events to the sync handler.
- [x] The handler resolves the Delivery Note's Sales Order to the order Synced Entity's `shopify_order_gid`.
- [x] On a genuine new fulfillment, `fulfillmentCreate` is called with line items/quantities matching the Delivery Note, mapped to Shopify variants via the variant Synced Entities from issue 05.
- [x] Partial fulfillment — a Delivery Note covering a subset of the Order's items/quantities — results in a `fulfillmentCreate` call scoped to just those items/quantities.
- [x] `shopify_fulfillment_gid` is stored on the Delivery Note's Custom Field, and the `fulfillment` Synced Entity is created/updated with both Fingerprints.
- [x] Echo detection prevents reprocessing a fulfillment state that already matches `erpnext_fingerprint` (no `ShopifyClient` calls).

## Blocked by

- 17-shopify-order-to-erpnext-so-si-pe.md
- 18-erpnext-sales-order-to-shopify-order.md

## Comments

- Implemented: `connector/sync/fulfillments.py::handle_delivery_note_submit` (plus `_order_entity_for_so`, `_fulfillment_entity`), `connector/fingerprint.py::_canonicalize_fulfillment` (tracks `line_items` as `(variant_gid, quantity)` pairs, so partial vs. full fulfillment states produce different Fingerprints). Wired as `POST /webhooks/erpnext/delivery-notes` in `connector/api/erpnext_webhooks.py`. Tests in `tests/sync/test_fulfillments.py`: creates a Shopify fulfillment from a Delivery Note, returns early without an order Synced Entity, Echo-safe on redelivery, and a partial-then-full fulfillment sequence producing two distinct `fulfillmentCreate` calls (4 tests). `pytest -q` passes (99 passed total).
