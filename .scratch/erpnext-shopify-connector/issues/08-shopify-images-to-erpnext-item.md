# Shopify product images → ERPNext Item image + File attachments

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 10, 11.

## What to build

Extend `canonicalize("product", ...)` from issue 05 to track image URLs (the featured image plus the ordered list of all media URLs) so Fingerprint changes detect image edits.

Extend the Shopify → ERPNext product sync handler from issue 05 (triggered by `products/update` carrying media changes) so that, on a genuine product update where images changed:

- The Shopify product's primary/featured image is downloaded and set as the ERPNext template Item's `image` field.
- All of the product's images are attached as Files linked to the ERPNext Item.

## Acceptance criteria

- [ ] `canonicalize("product", ...)` includes the featured image URL and the ordered list of all media URLs in its tracked fields; Fingerprint changes when images are added, removed, or reordered, and stays stable when untracked fields change.
- [ ] On a genuine product update where images changed, the sync handler sets the ERPNext template Item's `image` field to the Shopify product's featured image.
- [ ] All of the Shopify product's images are attached as Files linked to the ERPNext Item (verified against a fake `ERPNextClient`'s file-attach calls).
- [ ] Echo detection (image-only changes that match the stored Fingerprint) results in no `ERPNextClient` calls.
- [ ] Tests cover: first sync of a product with multiple images, and a later update that adds/removes an image.

## Blocked by

- 05-shopify-product-to-erpnext-item.md
