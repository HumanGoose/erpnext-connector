# ERPNext Item image/attachments → Shopify product media

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 12.

## What to build

Implement the ERPNext → Shopify direction of image sync, for sync-enabled Items (per issue 07). Extend `canonicalize("product", ...)` (ERPNext-side shape) to track the Item's `image` field and its attached image Files, consistent with the Shopify-side canonical fields from issue 08.

When a sync-enabled Item's `image` field or attached image Files change — after Echo detection against `erpnext_fingerprint` — the sync handler uploads the Item's `image` and attached Files to the corresponding Shopify product's media.

## Acceptance criteria

- [ ] `canonicalize("product", ...)` (ERPNext-side shape) tracks the Item's `image` field and attached image Files, consistent with the Shopify-side canonical fields from issue 08.
- [ ] A change to a sync-enabled Item's `image` or attached Files (Echo-checked against `erpnext_fingerprint`) uploads the corresponding image(s) to the Shopify product's media via `ShopifyClient`.
- [ ] Items without "Sync to Shopify" enabled are skipped, consistent with issue 07.
- [ ] Echo cases (image data unchanged per Fingerprint) make no calls to `ShopifyClient`.
- [ ] Tests cover: adding a new image to a synced Item, and changing the primary `image`.

## Blocked by

- 07-erpnext-item-to-shopify-product.md
- 08-shopify-images-to-erpnext-item.md
