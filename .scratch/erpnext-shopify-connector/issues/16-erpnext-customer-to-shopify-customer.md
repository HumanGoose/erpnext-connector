# ERPNext Customer → Shopify Customer sync

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 21.

## What to build

Implement the ERPNext → Shopify direction of customer sync. A Frappe Webhook fires on Customer create/update; the sync handler:

- Performs Echo detection against `erpnext_fingerprint` using `canonicalize("customer", ...)` from issue 15 applied to the ERPNext Customer shape.
- On a genuine change, creates or updates the corresponding Shopify Customer (storing the resulting `shopify_customer_gid` back onto the ERPNext Customer's Custom Field on first sync) and the Synced Entity row with refreshed Fingerprints.

## Acceptance criteria

- [x] Webhook receiver routes ERPNext Customer create/update events to the sync handler.
- [x] Echo detection using `canonicalize("customer", ...)` against `erpnext_fingerprint` prevents reprocessing the Connector's own writes from issue 15 (no `ShopifyClient` calls on match).
- [x] A genuine new ERPNext Customer (no existing Synced Entity) creates a corresponding Shopify Customer, writes `shopify_customer_gid` back to the ERPNext Customer, and creates a Synced Entity row with both Fingerprints.
- [x] A genuine update to an already-synced Customer's name/email/phone/address updates the corresponding Shopify Customer.

## Blocked by

- 15-shopify-customer-to-erpnext-customer.md

## Comments

- Implemented: `connector/sync/customers.py::handle_erpnext_customer_webhook` (plus `_shopify_customer_input`), sharing `canonicalize("customer", ...)`/`_canonicalize_customer` with issue 15 so both directions use one Fingerprint per Customer. Wired as `POST /webhooks/erpnext/customers` in `connector/api/erpnext_webhooks.py` (Frappe `after_insert`/`on_update`, per `connector/erpnext/setup.py`). Tests added to `tests/sync/test_customers.py`: a new ERPNext Customer creates a Shopify Customer (firstName/lastName split from `customer_name`, email/phone/addresses mapped) and writes `shopify_customer_gid` back plus a Synced Entity row with matching Fingerprints; a redelivered/unchanged Customer is Echo-safe; an email/phone update on an already-synced Customer calls `customerUpdate` with the new values and refreshes both Fingerprints (3 tests), plus HTTP routing in `tests/api/test_erpnext_webhooks.py`. `pytest -q` passes (114 passed total).
