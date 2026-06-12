# Recurring reconciliation pass (general framework)

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 17, 37.

## What to build

Implement a generic, recurring reconciliation job (APScheduler) that:

- Walks all Synced Entity rows.
- Re-fetches current data for each side: Shopify via Bulk Operations (`bulkOperationRunQuery`) for product/variant/inventory data at scale, ERPNext via list queries.
- Recomputes Fingerprints using each row's `entity_type`'s registered `canonicalize` function.
- Where a recomputed Fingerprint differs from the stored one on either side, enqueues the corresponding sync via the retry queue from issue 04, exactly as a webhook-driven change would.

The framework is generic over `entity_type` — driven by whatever `canonicalize` functions are registered at the time — and is demoed end-to-end against the `product`/`variant` and `inventory_level` entity types established in issues 05 and 12/13. Adding a new entity type's `canonicalize` function in a future issue should require no changes to this job.

## Acceptance criteria

- [ ] An APScheduler job runs on a configurable recurring schedule.
- [ ] The job walks all Synced Entity rows, re-fetches current Shopify-side data via Bulk Operations and ERPNext-side data via list queries, and recomputes both Fingerprints using the registered `canonicalize` function for each row's `entity_type`.
- [ ] Where a recomputed Fingerprint differs from the stored `shopify_fingerprint`/`erpnext_fingerprint`, the job enqueues a retry-queue entry in the appropriate `direction`, identical in shape to what the corresponding webhook handler would enqueue.
- [ ] Rows where both recomputed Fingerprints match the stored ones are left untouched (no enqueue).
- [ ] The framework is generic — adding a new entity_type's `canonicalize` function requires no changes to the reconciliation job itself.
- [ ] Tests demonstrate the pass against `product`/`variant` and `inventory_level` Synced Entities: one row with drift (enqueues a sync) and one row in sync (no-op).

## Blocked by

- 05-shopify-product-to-erpnext-item.md
- 12-erpnext-stock-to-shopify-inventory.md
- 13-shopify-inventory-to-erpnext-stock-reconciliation.md
