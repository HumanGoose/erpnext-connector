# Shopify variant price → ERPNext Item Price

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 13.

## What to build

Extend `canonicalize("variant", ...)` from issue 05 to track each Shopify ProductVariant's `price`. On a genuine price change detected via `products/update` (or a dedicated price-related topic if Shopify delivers one), the sync handler updates the corresponding ERPNext Item's Item Price record on the configured Price List (e.g. "Standard Selling") for that variant Item.

## Acceptance criteria

- [ ] `canonicalize("variant", ...)` includes `price` in its tracked fields; Fingerprint changes on price edits and stays stable otherwise.
- [ ] A genuine price change on a Shopify variant updates (or creates, if absent) the ERPNext Item Price record for the corresponding variant Item on the configured Price List.
- [ ] Echo detection (price unchanged per Fingerprint) results in no `ERPNextClient` calls.
- [ ] Tests cover: price change on a synced variant, and a no-op Echo case where the price already matches.

## Blocked by

- 05-shopify-product-to-erpnext-item.md
