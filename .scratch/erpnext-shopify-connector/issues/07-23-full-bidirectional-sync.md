# Full bidirectional sync (combined issues 07–23)

Status: in-progress

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 6–9, 10–14, 15–18, 19–21, 22–33.

## Why combined

Issues 07–23 are the full set of sync handlers built on the scaffolding,
clients, fingerprint/Echo machinery, and the Shopify→ERPNext product sync
(issues 01–06). They share three pieces of new foundation — a semantic
`ShopifyClientProtocol` (the ERPNext→Shopify directions need to *write* to
Shopify, not just `execute` GraphQL), an ERPNext-webhook receiver router, and
extensions to the `canonicalize` registry — so they are implemented together as
one coherent slice rather than 17 separate branches that would each re-touch the
same files.

## Scope (per original issue)

- **07** ERPNext Item → Shopify product/variant (create/update, opt-in)
- **08** Shopify product images → ERPNext Item image + File attachments
- **09** ERPNext Item image/attachments → Shopify product media
- **10** Shopify variant price → ERPNext Item Price
- **11** ERPNext Item Price → Shopify variant price
- **12** ERPNext stock receipt → Shopify inventory update
- **13** Shopify inventory change → ERPNext Stock Reconciliation
- **14** Recurring reconciliation pass (generic framework)
- **15** Shopify customer → ERPNext Customer
- **16** ERPNext Customer → Shopify Customer
- **17** Shopify Order → ERPNext Sales Order + Sales Invoice + Payment Entry
- **18** ERPNext Sales Order → Shopify Order (orderCreate, idempotent, paid)
- **19** ERPNext Delivery Note → Shopify Fulfillment (full/partial)
- **20** Shopify Fulfillment → ERPNext Delivery Note (full/partial)
- **21** Shopify Order cancellation → ERPNext SO/SI/PE cancellation cascade
- **22** ERPNext Sales Order cancellation → Shopify Order cancellation
- **23** Shopify refund → ERPNext credit note / refund Payment Entry

## New shared foundation

- `connector/shopify/client.py`: a `ShopifyClientProtocol` of semantic write
  methods (create/update product, create/update variants, append media, set
  inventory, create/update customer, create/cancel order, create fulfillment,
  create refund) implemented on the real `ShopifyClient` via GraphQL mutations,
  and faked in tests by `tests/shopify/fakes.py::FakeShopifyClient`.
- `connector/api/erpnext_webhooks.py`: FastAPI router for the Frappe-Webhook
  doctype callbacks registered in `connector/erpnext/setup.py` (Item, Item
  Price, Customer, Sales Order submit/cancel, Delivery Note, stock events).
- `connector/fingerprint.py`: `canonicalize` extended for `product` (images),
  `variant` (price), and added for `customer`, `order`, `inventory_level`,
  `fulfillment`. A `CANONICALIZERS` registry drives the generic reconciliation
  pass.

## Acceptance criteria

The per-issue acceptance criteria in `07`…`23` all hold, verified by the
automated test suite. Echo detection (no calls to the *other* system's client
on a Fingerprint match) is exercised for every handler.

## Comments

- Scope was narrowed to a vertical slice covering the full order lifecycle:
  issues **15** and **17–23** (Shopify customer sync plus order
  create/fulfillment/cancellation/refund in both directions) are implemented,
  wired to HTTP endpoints (`connector/api/shopify_webhooks.py` and the new
  `connector/api/erpnext_webhooks.py`, both registered in `connector/main.py`),
  and covered by tests (`tests/sync/test_customers.py`,
  `tests/sync/test_orders.py`, `tests/sync/test_fulfillments.py`,
  `tests/api/test_shopify_sync_webhooks.py`,
  `tests/api/test_erpnext_webhooks.py`). See each issue's own `## Comments` for
  implementation details.
- As a follow-up, issues **07**, **11**, and **16** (ERPNext → Shopify product
  + variant sync, ERPNext Item Price → Shopify variant price, and ERPNext
  Customer → Shopify Customer) were also implemented and wired as
  `POST /webhooks/erpnext/items`, `/webhooks/erpnext/item-prices`, and
  `/webhooks/erpnext/customers` in `connector/api/erpnext_webhooks.py`, using
  the pre-existing (previously unwired/untested) handlers in
  `connector/sync/products_to_shopify.py` and
  `connector/sync/customers.py::handle_erpnext_customer_webhook`. Tests added
  in `tests/sync/test_products_to_shopify.py` and `tests/sync/test_customers.py`.
  `pytest -q` now passes with 114 tests.
- Issues **08–10, 12–14** (Shopify product images/price → ERPNext, inventory
  sync in both directions, and the recurring reconciliation pass) remain
  unimplemented, unwired, and untested. The "New shared foundation" section
  above describing `connector/erpnext/setup.py` and a
  `CANONICALIZERS`-driven reconciliation registry exists and is partially used
  (Item/Item Price/Customer/Sales Order/Delivery Note webhooks are registered
  via `WEBHOOK_DOCTYPES`), but the inventory (`Stock Entry`/`Stock
  Reconciliation`) webhook routes and the reconciliation pass itself are not
  wired. If this remaining scope is picked up, it should be split into its own
  issue(s) rather than reusing this one.
