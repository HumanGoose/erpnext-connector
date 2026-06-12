# Shopify inventory change → ERPNext Stock Reconciliation

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 16, 18.

## What to build

Handle Shopify's inventory-level webhook (e.g. `inventory_levels/update`) for the configured Location. The sync handler:

- Resolves the inventory item to its Synced Entity (variant).
- Performs Echo detection against `shopify_fingerprint` for the `inventory_level` Synced Entity using `canonicalize("inventory_level", ...)` from issue 12.
- On a genuine change, applies the new absolute quantity to ERPNext via a Stock Reconciliation against the configured Warehouse.

## Acceptance criteria

- [ ] Webhook receiver routes Shopify inventory-level change events for the configured Location to the sync handler.
- [ ] On a genuine quantity change (Echo-checked via `canonicalize("inventory_level", ...)` / `shopify_fingerprint`), the handler creates an ERPNext Stock Reconciliation setting the absolute quantity for the corresponding Item at the configured Warehouse.
- [ ] Echo detection prevents reprocessing the Connector's own inventory writes from issue 12 (no `ERPNextClient` calls on match).
- [ ] Inventory changes at Locations other than the configured one are ignored.
- [ ] Tests cover: a genuine Shopify-side stock change, and an Echo case from a prior ERPNext→Shopify write.

## Blocked by

- 12-erpnext-stock-to-shopify-inventory.md
