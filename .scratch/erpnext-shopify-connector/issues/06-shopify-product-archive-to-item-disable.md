# Shopify product archive/delete → ERPNext Item disable

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 4.

## What to build

Extend the webhook receiver from issue 05 to handle the Shopify `products/delete` topic (and product-archived state changes, however Shopify represents them — confirm whether archiving is a distinct webhook topic or a status change delivered via `products/update`, and handle whichever applies).

The corresponding sync handler looks up the Synced Entity for the product's `shopify_product_gid`, and disables the corresponding ERPNext template Item and its variant Items (`disabled=1`) rather than deleting them — preserving historical records while marking the product as discontinued/unsellable in ERPNext.

## Acceptance criteria

- [x] Webhook receiver routes Shopify `products/delete` (and product-archived status changes, via whichever event Shopify actually delivers them) to a sync handler.
- [x] The handler looks up the Synced Entity by `shopify_product_gid` and disables the corresponding ERPNext template Item and all its variant Items, without deleting them.
- [x] Echo detection applies as in issue 05 — if the ERPNext Item is already disabled (matching stored Fingerprint state), no redundant write occurs.
- [x] A product with no corresponding Synced Entity (never synced) is handled gracefully (no error, no-op).
- [x] Tests assert the ERPNext disable call against a fake `ERPNextClient` and the resulting Synced Entity/Fingerprint state.

## Blocked by

- 05-shopify-product-to-erpnext-item.md

## Comments

- Implemented: `connector/sync/products.py` (`is_archived` — handles both REST `"archived"` and GraphQL `"ARCHIVED"` status casing; `handle_product_disable` — looks up the template Synced Entity by `shopify_product_gid`, disabling the template and all variant Items via `set_value("Item", ..., "disabled", 1)`, skipping the write if `get_doc` shows the Item is already disabled). `_gid()` extended to construct `gid://shopify/{resource}/{id}` from the numeric `id`-only `products/delete` payload shape (no `admin_graphql_api_id`). `connector/api/shopify_webhooks.py` routes `products/delete` and archived `products/update` to `handle_product_disable`. Tests in `tests/sync/test_product_disable.py` (6) and 2 added cases in `tests/api/test_shopify_webhooks.py`. `pytest -q` passes (58 passed total).
