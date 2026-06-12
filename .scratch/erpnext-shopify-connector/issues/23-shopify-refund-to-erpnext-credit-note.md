# Shopify refund → ERPNext credit note / refund Payment Entry

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 33.

## What to build

Handle the Shopify `refunds/create` webhook topic (HMAC-verified). The sync handler:

- Resolves the refund's order to its Synced Entity group and corresponding Sales Invoice.
- Performs Echo detection against the order/refund-related Fingerprint.
- On a genuine refund, creates the corresponding ERPNext credit note (return Sales Invoice) and/or refund Payment Entry reflecting the refunded line items and amounts.
- Updates Synced Entity/Fingerprint state to reflect the refund after a successful write.

## Acceptance criteria

- [x] Webhook receiver routes Shopify `refunds/create` (HMAC-verified) to the sync handler.
- [x] The handler resolves the refund's order to its Synced Entity group and corresponding Sales Invoice.
- [x] On a genuine refund, the handler creates an ERPNext credit note (return Sales Invoice) and/or refund Payment Entry reflecting the refunded line items and amounts.
- [x] Echo detection prevents reprocessing a refund already reflected in ERPNext per the stored Fingerprint (no `ERPNextClient` calls).
- [x] Synced Entity/Fingerprint state is updated to reflect the refund after a successful write.
- [x] Tests cover a full refund and a partial (line-item-subset) refund against a fake `ERPNextClient`.

## Blocked by

- 21-shopify-order-cancellation-cascade.md

## Comments

- Implemented: `connector/sync/orders.py::handle_shopify_refund_create` (plus `_refund_order_gid`, `_refund_gid`, `_refund_items`, `_refund_amount`). Dedup/Echo is via a `get_list("Sales Invoice", filters={"shopify_refund_gid": ...})` lookup rather than the `shopify_fingerprint`/`erpnext_fingerprint` pair (a refund is additive to an order group, so there's no single group Fingerprint to compare against). Wired as `POST /webhooks/shopify/refunds` (`refunds/create`, HMAC-verified) in `connector/api/shopify_webhooks.py`. Tests in `tests/sync/test_orders.py`: a full refund creates a credit-note Sales Invoice and a refund Payment Entry, a redelivered refund is a no-op, and a partial (single-line-item-of-two) refund only credits the refunded item (3 tests), plus HTTP routing in `tests/api/test_shopify_sync_webhooks.py`. `pytest -q` passes (99 passed total).
