# Shopify Fulfillment → ERPNext Delivery Note (full/partial)

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 29, 30.

## What to build

Implement the Shopify → ERPNext direction of fulfillment sync. A webhook receiver handles Shopify `fulfillments/create` (or order fulfillment-status update). The sync handler:

- Resolves the order to its order Synced Entity and the corresponding ERPNext Sales Order.
- Performs Echo detection against `shopify_fingerprint` for the `fulfillment` Synced Entity using `canonicalize("fulfillment", ...)` from issue 19.
- On a genuine new Shopify fulfillment, creates and submits a corresponding ERPNext Delivery Note for the fulfilled line items/quantities, mapped to ERPNext Items via the variant Synced Entities — supporting partial fulfillment.
- Updates the `fulfillment` Synced Entity with `shopify_fulfillment_gid`, the Delivery Note's `shopify_fulfillment_gid` Custom Field, and both Fingerprints.

## Acceptance criteria

- [x] Webhook receiver routes Shopify fulfillment-creation events (HMAC-verified) to the sync handler.
- [x] The handler resolves the Shopify Order to its order Synced Entity and the corresponding ERPNext Sales Order.
- [x] On a genuine new Shopify fulfillment, the handler creates and submits an ERPNext Delivery Note for the fulfilled line items/quantities, mapped to ERPNext Items via the variant Synced Entities.
- [x] Partial fulfillment — a Shopify fulfillment covering a subset of the Order's line items — results in a Delivery Note scoped to just those items/quantities.
- [x] The `fulfillment` Synced Entity is created/updated with `shopify_fulfillment_gid`, the Delivery Note's `shopify_fulfillment_gid` Custom Field, and both Fingerprints.
- [x] Echo detection prevents reprocessing a fulfillment that matches the stored `shopify_fingerprint` (no `ERPNextClient` calls), e.g. for the Connector's own write from issue 19.

## Blocked by

- 19-erpnext-delivery-note-to-shopify-fulfillment.md

## Comments

- Implemented: `connector/sync/fulfillments.py::handle_shopify_fulfillment_webhook` (plus `_fulfillment_order_gid`, `_fulfillment_gid`, `_order_customer`), reusing `_canonicalize_fulfillment`/`_fulfillment_entity` from issue 19 so both directions share one `fulfillment` Synced Entity per order group. Wired as `POST /webhooks/shopify/fulfillments` (`fulfillments/create`/`fulfillments/update`, HMAC-verified) in `connector/api/shopify_webhooks.py`. Tests in `tests/sync/test_fulfillments.py`: creates a submitted Delivery Note from a Shopify fulfillment, returns early without an order Synced Entity, and Echo-skips when the fulfillment matches the Connector's own write from issue 19 (3 tests), plus HTTP routing in `tests/api/test_shopify_sync_webhooks.py`. `pytest -q` passes (99 passed total).
