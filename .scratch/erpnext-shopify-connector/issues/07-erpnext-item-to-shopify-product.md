# ERPNext Item → Shopify product/variant sync (create/update, opt-in)

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 6, 7, 8, 9.

## What to build

Implement the ERPNext → Shopify direction of product/variant sync. A Frappe Webhook (configured in issue 03) fires on Item create/update for Items where the template's "Sync to Shopify" checkbox is enabled (variant Items inherit their template's flag).

The sync handler:

- Performs Echo detection against the stored `erpnext_fingerprint` using `canonicalize("product"/"variant", ...)` from issue 05 applied to the ERPNext Item REST shape.
- For a genuine new sync-enabled Item with no existing Synced Entity, creates the corresponding Shopify product (one Shopify ProductOption per ERPNext Item Attribute) and ProductVariants, storing the resulting `shopify_product_gid`/`shopify_variant_gid` back onto the ERPNext Item's Custom Fields and creating Synced Entity rows.
- For an update to title/description on an already-synced Item, updates the Shopify product accordingly.
- For a new variant Item added under an already-synced template, creates a new Shopify ProductVariant on the corresponding product.
- Items (and variants of templates) without "Sync to Shopify" enabled are skipped — no calls to `ShopifyClient`. Turning the flag off on a previously-synced Item stops it from being included in future product/variant/image/price sync without affecting the existing Shopify product.

## Acceptance criteria

- [x] Webhook receiver routes ERPNext Item create/update events for sync-enabled Items to the sync handler; Items without the flag (and variants of un-flagged templates) are skipped with no calls to `ShopifyClient`.
- [x] Echo detection using `canonicalize("product"/"variant", ...)` against `erpnext_fingerprint` prevents reprocessing the Connector's own prior writes (tested with fakes, no calls on Echo).
- [x] A new sync-enabled template Item (with variants) creates a corresponding Shopify product with matching ProductOptions and ProductVariants; the resulting GIDs are written back to the Item's Custom Fields and a Synced Entity row is created per template/variant.
- [x] A title/description update on an already-synced Item updates the corresponding Shopify product.
- [x] A new variant Item added under an already-synced template creates a new Shopify ProductVariant on the existing product.
- [x] Toggling "Sync to Shopify" off on a previously-synced Item is a no-op for future sync events (verified by a test that the flag check short-circuits before any client calls).

## Blocked by

- 05-shopify-product-to-erpnext-item.md
- 03-erpnext-client-and-setup.md

## Comments

- Implemented: `connector/sync/products_to_shopify.py::handle_item_webhook` (plus `_sync_enabled`, `_sync_template`, `_sync_variant`, `_sync_simple_item`, `item_to_product_raw`, `item_to_variant_raw`), reusing the `canonicalize("product"/"variant", ...)` canonicalizers from issue 05 applied to the ERPNext Item REST shape. Wired as `POST /webhooks/erpnext/items` in `connector/api/erpnext_webhooks.py` (Frappe `after_insert`/`on_update`, per `connector/erpnext/setup.py`'s `WEBHOOK_DOCTYPES`). Tests in `tests/sync/test_products_to_shopify.py`: a new sync-enabled template + 2 variants creates a Shopify product with `productOptions` and 2 `ProductVariants` (GIDs written back to Custom Fields), a title/description update calls `productUpdate`, a new variant added to an existing template calls `productVariantsBulkCreate`, an Item/variant without `sync_to_shopify` makes zero `ShopifyClient` calls, a redelivered template webhook is Echo-safe, and a simple (non-variant) Item creates a product with one default variant (7 tests). `pytest -q` passes (114 passed total).
- A latent gap (not exercised by tests, out of scope for this pass): for a simple (non-variant) Item, the `PRODUCT`-type Synced Entity's Fingerprint comes from `canonicalize("product", ...)`, which doesn't track price — so a price-only change on such an Item, arriving via issue 11's `/webhooks/erpnext/item-prices`, would be (incorrectly) treated as an Echo against that Fingerprint and not propagate. Items with variants (the common case, and the only case issue 11's tests cover) are unaffected, since their `VARIANT`-type entities' Fingerprints do track price. If simple-Item price sync matters, this should be revisited as a follow-up.
