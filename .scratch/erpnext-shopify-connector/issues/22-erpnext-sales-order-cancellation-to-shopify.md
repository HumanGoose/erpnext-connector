# ERPNext Sales Order cancellation → Shopify Order cancellation

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 32.

## What to build

A Frappe Webhook fires on Sales Order cancellation. The sync handler:

- Resolves the Sales Order's `shopify_order_gid`.
- Performs Echo detection against `erpnext_fingerprint` — a cancellation that already originated from Shopify (per issue 21's Fingerprint update) is a no-op.
- For a genuine ERPNext-originated cancellation where the Order has not yet been fulfilled and Shopify's API permits cancellation at its current state, cancels the corresponding Shopify Order.
- Where Shopify's API does not permit cancellation (e.g. already fulfilled), records this outcome rather than erroring or retrying indefinitely.

## Acceptance criteria

- [x] Webhook receiver routes ERPNext Sales Order cancellation events to the sync handler.
- [x] Echo detection: a cancellation that already originated from Shopify (per issue 21's Fingerprint update) results in no `ShopifyClient` calls.
- [x] For a genuine ERPNext-originated cancellation where the Shopify Order is still in a cancellable state, the handler calls Shopify's order-cancellation mutation and updates the Synced Entity's Fingerprints.
- [x] For an Order in a non-cancellable Shopify state (e.g. already fulfilled), the handler does not error — it records the outcome (e.g. via the retry queue's `last_error` or a logged note) without retrying indefinitely.
- [x] Tests cover both the cancellable and non-cancellable cases against a fake `ShopifyClient`.

## Blocked by

- 18-erpnext-sales-order-to-shopify-order.md
- 21-shopify-order-cancellation-cascade.md

## Comments

- Implemented: `connector/sync/orders.py::handle_erpnext_sales_order_cancel`, using `CANCELLED_FINGERPRINT` (issue 21) for Echo detection and `connector/retry_queue.py` (`enqueue` + `record_failure(..., max_attempts=1)`) to immediately dead-letter a non-cancellable Shopify order rather than erroring or retrying. Wired as `POST /webhooks/erpnext/sales-orders` in `connector/api/erpnext_webhooks.py`, disambiguated from issue 18's submit handler via the payload's `docstatus` (2 = cancel). Tests in `tests/sync/test_orders.py`: cancels the Shopify order and marks the group cancelled, Echo-skips if the cancellation already originated from Shopify, and a non-cancellable order (`FakeShopifyClient.non_cancellable`) produces a `dead_letter` Retry Queue entry without marking the group cancelled (3 tests). `pytest -q` passes (99 passed total).
