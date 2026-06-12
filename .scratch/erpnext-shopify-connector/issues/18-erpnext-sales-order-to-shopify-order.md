# ERPNext Sales Order → Shopify Order (orderCreate, idempotent, paid)

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 25, 26, 27.

## What to build

Implement the ERPNext → Shopify direction of order sync. A Frappe Webhook fires on Sales Order submission; the sync handler:

- Checks whether the Sales Order already carries a `shopify_order_gid` — its presence indicates the order originated from (or has already been pushed to) Shopify, so this is a no-op for this direction.
- For a genuine ERPNext-originated Sales Order (no `shopify_order_gid`), calls Shopify's `orderCreate` mutation with the `@idempotent` directive (per ADR-0001), using a stable idempotency key derived from the Sales Order so retries after a failed/uncertain attempt cannot create duplicate Shopify orders.
- Maps line items to Shopify variants via the variant Synced Entities from issue 05.
- Marks the resulting Shopify Order as already paid via `orderCreate`'s payment/transaction input, so Shopify doesn't show an outstanding balance for an order ERPNext already considers settled.
- Writes the resulting `shopify_order_gid` back to the Sales Order and Sales Invoice, and creates Synced Entity rows for the order group.

## Acceptance criteria

- [x] Webhook receiver routes ERPNext Sales Order submission events to the sync handler.
- [x] A Sales Order that already carries `shopify_order_gid` is a no-op (no `ShopifyClient` calls) — verified by a test.
- [x] A genuine ERPNext-originated Sales Order (no `shopify_order_gid`) calls `orderCreate` with the `@idempotent` directive and a stable idempotency key derived from the Sales Order, with line items mapped to Shopify variants via the variant Synced Entities.
- [x] The created Shopify Order is marked as already paid via `orderCreate`'s payment/transaction input (no outstanding balance).
- [x] `shopify_order_gid` is written back to the Sales Order and Sales Invoice, and a Synced Entity row is created for the order group.
- [x] A retried call (simulating a prior failed/uncertain attempt with the same idempotency key) does not create a second Shopify Order — verified against a fake `ShopifyClient` that enforces idempotency-key dedup.

## Blocked by

- 17-shopify-order-to-erpnext-so-si-pe.md

## Comments

- Implemented: `connector/sync/orders.py::handle_erpnext_sales_order_submit` (plus `_so_as_order`, `_linked_sales_invoice`). The `@idempotent` directive itself lives in `connector/shopify/mutations.py::ORDER_CREATE` (issue 02); `idempotency_key = f"erpnext-sales-order-{so_name}"`. Wired as `POST /webhooks/erpnext/sales-orders` in `connector/api/erpnext_webhooks.py`, disambiguated from issue 22's cancel handler via the Frappe Webhook payload's `docstatus` (1 = submit, 2 = cancel — both docevents share this path per `erpnext/setup.py::WEBHOOK_DOCTYPES`). Tests in `tests/sync/test_orders.py`: creates Shopify order from a Sales Order, no-op when `shopify_order_gid` already set, and idempotency-key dedup on redelivery (3 tests), plus HTTP routing in `tests/api/test_erpnext_webhooks.py`. `pytest -q` passes (99 passed total).
