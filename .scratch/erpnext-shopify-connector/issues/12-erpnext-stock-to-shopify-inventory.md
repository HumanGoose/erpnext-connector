# ERPNext stock receipt → Shopify inventory update

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 15, 18.

## What to build

Implement `canonicalize("inventory_level", ...)` tracking the absolute available quantity at the configured Location/Warehouse pair for a given Synced Entity (variant), plus its Fingerprint.

A Frappe Webhook fires on stock-affecting ERPNext transactions (e.g. Stock Entry/Stock Reconciliation affecting the configured Warehouse) for sync-enabled Items. The sync handler:

- Computes the new absolute quantity for the affected Item at the configured Warehouse.
- Performs Echo detection against `erpnext_fingerprint` for the `inventory_level` Synced Entity.
- On a genuine change, sets the corresponding Shopify variant's available inventory at the configured Location to that absolute quantity (via the inventory item's `shopify_inventory_item_gid`).

Both directions of inventory sync normalize a stock change to "set the absolute available quantity to N" for the configured Location/Warehouse pair (no multi-location/multi-warehouse splitting).

## Acceptance criteria

- [ ] `canonicalize("inventory_level", ...)` produces a canonical form keyed on the absolute available quantity at the configured Location/Warehouse; Fingerprint reflects quantity changes only.
- [ ] A stock receipt (or other stock-affecting transaction) at the configured Warehouse for a sync-enabled Item, resulting in a genuine quantity change, sets the Shopify variant's inventory at the configured Location to the new absolute quantity via `ShopifyClient`.
- [ ] Echo detection (quantity unchanged per Fingerprint, e.g. from the Connector's own write in issue 13) results in no `ShopifyClient` calls.
- [ ] Items/Warehouses outside the configured Location↔Warehouse pairing are ignored.
- [ ] Tests cover: a stock receipt changing quantity, and an Echo case where the quantity already matches.

## Blocked by

- 05-shopify-product-to-erpnext-item.md
- 01-connector-scaffolding.md
