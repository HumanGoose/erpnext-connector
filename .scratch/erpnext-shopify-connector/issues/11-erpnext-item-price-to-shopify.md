# ERPNext Item Price → Shopify variant price

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 14.

## What to build

Implement the ERPNext → Shopify direction of price sync for sync-enabled Items. A Frappe Webhook fires on Item Price changes for the configured Price List; the sync handler resolves the Item Price's Item to its Synced Entity, performs Echo detection against `erpnext_fingerprint` (extended with the price field per issue 10's canonical form), and on a genuine change updates the corresponding Shopify variant's `price`.

## Acceptance criteria

- [x] Webhook receiver routes Item Price change events (on the configured Price List) for sync-enabled Items to the sync handler.
- [x] `canonicalize("variant", ...)` (ERPNext-side) includes the Item Price value, consistent with issue 10's canonical fields.
- [x] A genuine price change updates the corresponding Shopify variant's `price` via `ShopifyClient`.
- [x] Echo detection prevents reprocessing the Connector's own price writes from issue 10 (no calls on match).
- [x] Items not flagged for sync (or whose template isn't) are skipped.

## Blocked by

- 07-erpnext-item-to-shopify-product.md
- 10-shopify-price-to-erpnext-item-price.md

## Comments

- Implemented: `connector/sync/products_to_shopify.py::handle_item_price_webhook` (plus `_variant_price`), gated on `price_list == "Standard Selling"` (the configured Price List) and `_sync_enabled`. Resolves the priced Item to its `variant` Synced Entity (or, for a simple Item, its `product` entity) and Echo-checks `canonicalize("variant", item_to_variant_raw(...))`'s Fingerprint — which already includes `price` per issue 10's `_canonicalize_variant`/`_money` — against `erpnext_fingerprint` before calling `update_variant_price`. Wired as `POST /webhooks/erpnext/item-prices` in `connector/api/erpnext_webhooks.py` (Frappe `after_insert`/`on_update` on Item Price, per `connector/erpnext/setup.py`). Tests in `tests/sync/test_products_to_shopify.py`: a new Item Price for a synced variant calls `productVariantsBulkUpdate` with the normalized price and refreshes both Fingerprints, a redelivered/unchanged price is Echo-safe (no `ShopifyClient` calls), and an Item Price for an Item without `sync_to_shopify` makes zero calls (3 tests). `pytest -q` passes (114 passed total). See issue 07's Comments for a known gap on simple (non-variant) Items.
