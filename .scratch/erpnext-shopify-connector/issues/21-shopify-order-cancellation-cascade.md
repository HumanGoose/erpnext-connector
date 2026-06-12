# Shopify Order cancellation → ERPNext SO/SI/PE cancellation cascade

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 31.

## What to build

Handle the Shopify `orders/cancelled` webhook topic (HMAC-verified). The sync handler:

- Resolves the order's Synced Entity group to its ERPNext Sales Order, Sales Invoice, and Payment Entry.
- Cascades cancellation: cancels the Sales Order; depending on the Sales Invoice's current state, cancels it directly or issues a credit note against it (e.g. if it's already paid/reconciled and a straight cancel isn't possible); reverses the associated Payment Entry.
- Performs Echo detection: if the ERPNext documents are already in the cancelled/credited state matching the stored `erpnext_fingerprint`, no further `ERPNextClient` calls are made.
- Refreshes Synced Entity Fingerprints to reflect the cancelled state after a successful cascade.

## Acceptance criteria

- [x] Webhook receiver routes Shopify `orders/cancelled` (HMAC-verified) to the sync handler.
- [x] The handler resolves the order's Synced Entity group to its Sales Order, Sales Invoice, and Payment Entry.
- [x] Cancellation cascades correctly: the Sales Order is cancelled; the Sales Invoice is cancelled if cancellable, or credited via a credit note if not; the Payment Entry is reversed.
- [x] Echo detection: if the ERPNext documents are already in the cancelled/credited state matching the stored `erpnext_fingerprint`, no further `ERPNextClient` calls are made.
- [x] Synced Entity Fingerprints are refreshed to reflect the cancelled state after a successful cascade.
- [x] Tests cover cancellation of an order before fulfillment (straightforward cancel) and after invoicing (credit-note path), against a fake `ERPNextClient`.

## Blocked by

- 17-shopify-order-to-erpnext-so-si-pe.md

## Comments

- Implemented: `connector/sync/orders.py::handle_shopify_order_cancel` (plus `_reverse_payment`, `_cancel_or_credit_invoice`, `_cancel_sales_order`, `_mark_group_cancelled`), and the shared `CANCELLED_FINGERPRINT` sentinel (`fingerprint({"order_state": "cancelled"})`) used for Echo detection in both this issue and issue 22. Wired as `POST /webhooks/shopify/orders` (`orders/cancelled` topic, HMAC-verified) in `connector/api/shopify_webhooks.py`. Tests in `tests/sync/test_orders.py`: unpaid order cascades cancellation across SO/SI/PE, a "Paid" invoice gets a credit note instead of a direct cancel, and a re-delivered cancellation is Echo-safe (3 tests). `pytest -q` passes (99 passed total).
