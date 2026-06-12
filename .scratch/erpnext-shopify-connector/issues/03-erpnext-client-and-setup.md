# ERPNext client + setup routine: Custom Fields & Frappe Webhooks

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 41.

## What to build

Build an `ERPNextClient` wrapper around `frappeclient` for the REST calls the Connector needs, with a Protocol interface suitable for faking in sync-handler tests (per the PRD's Testing Decisions).

Implement a setup routine that provisions the ERPNext-side Custom Fields the Connector depends on:

- On Item (template and variant): `shopify_product_gid` (template-level), `shopify_variant_gid` (variant-level), `shopify_inventory_item_gid`.
- On Item (template only): a "Sync to Shopify" checkbox.
- On Customer: `shopify_customer_gid`.
- On Sales Order / Sales Invoice: `shopify_order_gid`.
- On Delivery Note: `shopify_fulfillment_gid`.

The same routine configures standard Frappe Webhook doctype entries that POST to the Connector's webhook-receiver endpoints for the Item, Customer, Sales Order, and Delivery Note doctypes (create/update/submit/cancel events as needed by later slices).

## Acceptance criteria

- [ ] An `ERPNextClient` wraps `frappeclient` for document CRUD and Custom Field/Webhook administration, with a Protocol interface suitable for faking.
- [ ] A setup routine creates all Custom Fields listed above on the correct doctypes if they don't already exist, and is idempotent (re-running doesn't error or duplicate fields).
- [ ] The same routine creates Frappe Webhook configurations pointing at the Connector's webhook-receiver endpoints for Item, Customer, Sales Order, and Delivery Note doctypes, idempotently.
- [ ] Tests run against a fake/mock `frappeclient` — no live ERPNext instance is required to pass the suite.

## Blocked by

- 01-connector-scaffolding.md

## Comments

- Implemented: `connector/erpnext/client.py` (`ERPNextClientProtocol` covering get_doc/get_list/insert/update/delete/submit/cancel/set_value, and `ERPNextClient` wrapping `frappeclient.FrappeClient`), `connector/erpnext/setup.py` (`register_custom_fields` for the 8 Custom Fields across Item/Customer/Sales Order/Sales Invoice/Delivery Note, `register_webhooks` creating Frappe Webhook configs for Item/Customer (after_insert, on_update), Sales Order (on_submit, on_cancel), Delivery Note (on_submit) — both idempotent via `get_list` existence checks — plus a `main()` CLI entrypoint). Added `tests/erpnext/fakes.py` (`FakeERPNextClient`, an in-memory Protocol implementation reusable by later sync-handler tests per the PRD's testing decisions). Tests in `tests/erpnext/` cover `ERPNextClient` against a mocked `FrappeClient` and the setup routine's idempotency against `FakeERPNextClient` — no live ERPNext required. `pytest -q` passes (18 passed total).
- Note for manual e2e validation (issue 24): `webhook_json` template (`{{ doc.as_dict() | tojson }}`) and Custom Field `insert_after` placements should be confirmed against the actual ERPNext version in use.
