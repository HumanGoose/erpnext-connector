# ERPNext ↔ Shopify Connector

Status: ready-for-agent

## Problem Statement

The business runs its storefront on Shopify and its inventory, accounting, and fulfillment operations on ERPNext. Today these two systems don't talk to each other: products, prices, and stock levels have to be entered or updated twice, orders placed on Shopify don't appear in ERPNext's sales and accounting records, and fulfillment or cancellation in one system doesn't show up in the other. This creates duplicate data-entry work, a constant risk of the two systems drifting out of sync (overselling stock that's actually unavailable, invoices that don't match what was actually sold, customers who don't exist where staff expect them), and no single place staff can trust as "the current state of an order or product."

Staff also need the freedom to work from either system — a warehouse team might record a sale or stock count directly in ERPNext, while online orders and product edits happen in Shopify — without worrying about which system is "authoritative" or having to manually reconcile the two afterwards.

## Solution

Build a standalone **Connector** service that keeps Products, Variants, Images, Pricing, Inventory, Customers, and Orders (including fulfillment and cancellation status) synchronized in both directions between Shopify and ERPNext, in near real time, without changing how either system fundamentally works.

ERPNext stays a stock/unmodified system aside from a small number of Custom Fields (to cross-reference Shopify records and to opt individual Items into product sync) and standard Frappe Webhook configurations. Shopify stays a stock store aside from a custom app with the necessary API scopes and webhook subscriptions.

The Connector tracks every record it keeps in sync as a **Synced Entity** — a pairing of one Shopify record and one ERPNext record (or document set) representing the same real-world thing. For each Synced Entity, the Connector stores a **Fingerprint** of the data on each side, so that when its own write to a system causes that system to notify it back (an **Echo**), the Connector recognizes and discards the notification instead of looping. Real-time sync is driven by webhooks from both systems; a periodic reconciliation pass acts as a backstop that catches anything a webhook missed (e.g. due to downtime or delivery failure).

## User Stories

### Products & Variants

1. As a merchandiser, I want a new product created in Shopify to automatically appear as an Item in ERPNext, so that inventory and accounting staff can manage it without manual data entry.
2. As a merchandiser, I want a Shopify product with multiple variants (e.g. Size/Color) to appear in ERPNext as a template Item with variant Items underneath it, so that ERPNext's variant-based stock and pricing model stays accurate.
3. As a merchandiser, I want edits to a product's title or description in Shopify to update the corresponding ERPNext Item, so that ERPNext always reflects the current customer-facing listing.
4. As a merchandiser, I want a product archived or deleted in Shopify to be reflected by disabling the corresponding Item in ERPNext, so that discontinued products don't appear sellable in ERPNext.
5. As a merchandiser, I want new variants added to an existing Shopify product to appear as new variant Items under the corresponding template Item in ERPNext.
6. As an inventory manager, I want to create a new Item in ERPNext and mark it to be synced, so that it's automatically created as a product in the Shopify store.
7. As an inventory manager, I want edits to a synced Item's title or description in ERPNext to update the corresponding Shopify product.
8. As an inventory manager, I want a new variant Item added under a synced template Item in ERPNext to automatically appear as a new variant on the corresponding Shopify product.
9. As an inventory manager, I want to turn off syncing for an Item without deleting it from either system, so that I can manage which products are exposed to Shopify on a per-Item basis.

### Images

10. As a merchandiser, I want a Shopify product's primary image to appear as the corresponding ERPNext Item's image, so that staff can visually identify items in the ERPNext UI.
11. As a merchandiser, I want all of a Shopify product's images to be available as file attachments on the corresponding ERPNext Item, so that no product imagery is lost when viewing the item in ERPNext.
12. As an inventory manager, I want an image I attach to a synced ERPNext Item to be uploaded to the corresponding Shopify product, so that I can manage product photography from ERPNext if needed.

### Pricing

13. As a merchandiser, I want a price change on a Shopify variant to update the corresponding ERPNext Item's selling price, so that ERPNext quotes and invoices reflect the live storefront price.
14. As a pricing manager, I want a price change on a synced ERPNext Item to update the corresponding Shopify variant's price, so that I can manage pricing centrally from ERPNext.

### Inventory

15. As a warehouse manager, I want a stock receipt recorded in ERPNext to update the corresponding Shopify variant's available inventory, so that the storefront doesn't oversell items that are actually in stock or out of stock.
16. As a warehouse manager, I want a sale, return, or stock adjustment that changes inventory in Shopify to update the corresponding Item's stock level in ERPNext, so that ERPNext's stock ledger reflects reality.
17. As a warehouse manager, I want inventory levels to be checked on a recurring schedule (not only when a webhook fires), so that any update missed by a webhook is caught and corrected automatically.
18. As a warehouse manager, I want inventory sync to apply to one configured Shopify Location mapped to one ERPNext Warehouse, so that stock isn't ambiguously split across multiple locations during this phase.

### Customers

19. As a sales rep, I want a customer who places an order on Shopify to automatically appear as a Customer record in ERPNext, so that I don't have to manually create customer records for online orders.
20. As a sales rep, I want updates to a customer's name, email, phone, or address made in Shopify to update the corresponding ERPNext Customer record.
21. As a sales rep, I want a Customer created or edited in ERPNext to be reflected in Shopify, so that customer records stay consistent if staff manage customers from ERPNext.

### Orders

22. As an order processor, I want a new Shopify Order to automatically create a corresponding Sales Order in ERPNext, so that fulfillment and accounting teams see new orders without manual entry.
23. As an accountant, I want a new Shopify Order — which is pre-paid — to automatically create a Sales Invoice and a Payment Entry in ERPNext alongside the Sales Order, so that revenue and payment are recorded without manual bookkeeping.
24. As an order processor, I want the line items, quantities, prices, taxes, shipping charges, and discounts on a Shopify Order to be accurately reflected on the corresponding ERPNext Sales Order and Sales Invoice, so that financial totals match between systems.
25. As a sales rep, I want to create a Sales Order directly in ERPNext (e.g. for a phone or in-person sale) and have it create a corresponding Order in Shopify, so that all orders — regardless of where they originated — are visible in the Shopify admin.
26. As a sales rep, I want an Order created in Shopify from an ERPNext Sales Order to be marked as already paid, so that Shopify's order status doesn't show an outstanding balance for an order ERPNext already considers settled.
27. As an order processor, I want order creation in either direction to be safe to retry without creating duplicate orders, so that transient failures during order sync don't double-charge or double-ship a customer.

### Fulfillment

28. As a warehouse manager, I want submitting a Delivery Note in ERPNext for an Order's items to mark the corresponding Order as fulfilled in Shopify, so that the customer receives Shopify's shipping notification.
29. As a warehouse manager, I want a Fulfillment recorded directly in Shopify to be reflected as a submitted Delivery Note in ERPNext, so that ERPNext's stock ledger and order status stay accurate regardless of where fulfillment was recorded.
30. As a warehouse manager, I want partial fulfillment — shipping some but not all items on an Order — to be reflected accurately in both systems.

### Cancellations & Refunds

31. As an order processor, I want cancelling an Order in Shopify to cancel the corresponding Sales Order in ERPNext (and cancel or credit-note the Sales Invoice and reverse the Payment Entry as needed), so that ERPNext's books stay accurate.
32. As an order processor, I want cancelling the Sales Order in ERPNext to cancel the corresponding Order in Shopify where Shopify's API allows it, so that the storefront and customer-facing notifications reflect the cancellation.
33. As an accountant, I want a refund issued in Shopify to create the corresponding credit note or refund records in ERPNext, so that financial records match.

### Sync Reliability & Operations

34. As a developer, I want every inbound change to be checked against the stored Fingerprint for that Synced Entity before being processed, so that the Connector's own writes don't trigger an Echo that re-processes as if it were a new change.
35. As an operations engineer, I want failed sync operations to be retried automatically with increasing delay between attempts, so that transient errors like network blips or rate limits don't require manual intervention.
36. As an operations engineer, I want sync operations that fail repeatedly to be moved to a dead-letter queue with the error recorded, so that I can investigate and resolve persistent failures without losing the original change.
37. As an operations engineer, I want a recurring reconciliation pass that compares Shopify and ERPNext state for all Synced Entities, so that any change missed by webhooks — for any reason — is eventually corrected.
38. As an operations engineer, I want to query the current state of Synced Entities and the retry/dead-letter queue, so that I can monitor sync health and investigate issues.

### Setup & Configuration

39. As a developer setting up the Connector, I want to configure the Shopify app credentials, webhook secret, and the Location↔Warehouse pairing via configuration (not code), so that the Connector can be deployed to different environments without code changes.
40. As a developer, I want the Connector to register its required Shopify webhook subscriptions, so that Shopify begins notifying it of changes without manual setup in the Shopify admin.
41. As a developer, I want the required ERPNext Custom Fields (Shopify ID cross-references, the per-Item sync flag) and Frappe Webhook configurations to be created via a setup routine, so that ERPNext is prepared for syncing without hand-configuring doctypes.

## Implementation Decisions

### Architecture

- The Connector is a standalone Python/FastAPI service (per ADR-0002), separate from both Shopify and ERPNext. It talks to Shopify exclusively via the GraphQL Admin API (per ADR-0001) and to ERPNext via its REST API through `frappeclient`.
- ERPNext remains otherwise stock. The only changes made to it are: a small set of Custom Fields (below), and standard Frappe Webhook doctype configurations that POST to the Connector's webhook-receiver endpoints when relevant ERPNext documents change.
- Shopify remains a stock store aside from a custom app (with `read/write` scopes for products, inventory, orders, customers, and fulfillments, and an offline access token) and its webhook subscriptions, registered via `webhookSubscriptionCreate`.

### ERPNext-side Custom Fields

- On Item (template and variant): `shopify_product_gid` (template-level), `shopify_variant_gid` (variant-level), `shopify_inventory_item_gid`.
- On Item (template only): a "Sync to Shopify" checkbox — the explicit per-Item opt-in for product/variant/image/price sync. Variant Items inherit their template's sync status.
- On Customer: `shopify_customer_gid`.
- On Sales Order / Sales Invoice: `shopify_order_gid`. Presence of this field on a Sales Order indicates it originated from (or has already been synced to) Shopify — used to distinguish ERPNext-originated orders that still need to be pushed to Shopify from ones that don't.
- On Delivery Note: `shopify_fulfillment_gid`.

Customers and Orders sync unconditionally in both directions — there is no opt-in flag for them, since they arise as a natural consequence of order activity on either side. The "Sync to Shopify" flag applies only to the product catalog (Items/Variants/Images/Pricing).

### Product & Variant mapping

- A Shopify Product with one or more `options` (e.g. Size, Color) and multiple Variants maps to an ERPNext template Item (`has_variants = 1`), with one Item Attribute per Shopify product option, and one ERPNext variant Item per Shopify ProductVariant (`variant_of = <template item code>`, with attribute values matching the variant's `selectedOptions`).
- A Shopify Product with only its single default variant maps to one non-variant ERPNext Item.
- SKU is the human-readable join key for initial matching; the Shopify GIDs stored in the Custom Fields above are the canonical identifiers used by the Synced Entity store going forward.

### Pricing mapping

- A Shopify variant's `price` corresponds to an ERPNext Item Price record on a single configured Price List (e.g. the default "Standard Selling" price list) for the corresponding Item/variant Item.

### Image mapping

- A Shopify product's primary/featured image corresponds to the ERPNext Item's `image` field.
- All of a Shopify product's images correspond to File attachments linked to the ERPNext Item.
- In the ERPNext → Shopify direction, the Item's `image` field and its attached image Files correspond to the Shopify product's media.

### Inventory mapping

- A single configured Shopify Location is paired with a single configured ERPNext Warehouse for this phase (no multi-location/multi-warehouse splitting).
- Both directions normalize a stock change to "set the absolute available quantity to N" for the paired Location/Warehouse.
- On the ERPNext side, inventory pushes from Shopify are applied via Stock Reconciliation.
- The reconciliation pass uses Shopify Bulk Operations to read inventory levels at scale and compares them against ERPNext stock for all Synced Entities of type `product`/`variant`.

### Customer mapping

- A Shopify Customer corresponds to an ERPNext Customer. Synced fields: name, email, phone, and addresses.

### Orders & related documents

- When a Shopify Order arrives (and is not recognized as an Echo), the Connector creates, together, an ERPNext Sales Order, a Sales Invoice, and a Payment Entry — reflecting that Shopify orders are pre-paid at the point of creation.
- Line items, quantities, prices, taxes, shipping charges, and discounts from the Shopify Order are carried onto the Sales Order/Sales Invoice so that totals reconcile between systems.
- When an ERPNext Sales Order is submitted that does **not** already carry a `shopify_order_gid` (i.e. it did not originate from Shopify), the Connector creates a corresponding Order in Shopify via `orderCreate`, marked as already paid (using `orderCreate`'s payment/transaction input) so Shopify doesn't show an outstanding balance for an order ERPNext already considers settled.
- `orderCreate` calls use the `@idempotent` directive (per ADR-0001) so that retries after a failed/uncertain attempt cannot create duplicate Shopify orders.

### Fulfillment

- **Fulfillment** is the bidirectional order-status signal between the two systems (per CONTEXT.md):
  - ERPNext: a submitted Delivery Note for an Order's items.
  - Shopify: a fulfillment record on the Order, created via `fulfillmentCreate`.
- A Delivery Note submission triggers `fulfillmentCreate` for the corresponding line items on the Shopify Order; a Shopify fulfillment triggers creation and submission of the corresponding Delivery Note in ERPNext.
- Partial fulfillment (a subset of an Order's line items/quantities) is supported in both directions, matching line items by their Shopify variant / ERPNext Item references.

### Cancellations & refunds

- Cancelling the Shopify Order cascades to cancelling the ERPNext Sales Order, and — depending on its current state — cancelling/crediting the Sales Invoice and reversing the Payment Entry.
- Cancelling the ERPNext Sales Order (where not yet fulfilled) cascades to cancelling the corresponding Order in Shopify, where the Shopify API permits cancellation at that Order's current state.
- A Shopify refund creates the corresponding credit note / refund Payment Entry in ERPNext.

### Synced Entity / Fingerprint / retry queue (conceptual schema)

Two persistent stores, backed by SQLModel + SQLite (per ADR-0002):

**Synced Entity** — one row per Shopify↔ERPNext record pairing:

| Field | Purpose |
|---|---|
| `entity_type` | `product`, `variant`, `image`, `customer`, `order`, `fulfillment`, `inventory_level`, etc. |
| `shopify_gid` | Shopify GraphQL global ID |
| `erpnext_doctype` + `erpnext_name` | ERPNext document reference (a single `entity_type` like `order` may reference multiple ERPNext documents — Sales Order, Sales Invoice, Payment Entry, Delivery Note — each tracked as its own Synced Entity row linked by a shared group key) |
| `shopify_fingerprint` | Fingerprint of the Shopify-side data as of the last write/read by the Connector |
| `erpnext_fingerprint` | Fingerprint of the ERPNext-side data as of the last write/read by the Connector |
| `last_synced_at` | timestamp |

**Retry queue** — one row per pending/failed sync operation:

| Field | Purpose |
|---|---|
| `synced_entity_id` | nullable FK — null for operations that create a new Synced Entity |
| `direction` | `shopify_to_erpnext` or `erpnext_to_shopify` |
| `entity_type` | as above |
| `payload` | the change to apply, captured at enqueue time |
| `attempt_count`, `next_attempt_at` | backoff bookkeeping |
| `status` | `pending`, `in_progress`, `dead_letter`, `completed` |
| `last_error` | most recent failure detail |

### Echo detection

On every inbound webhook or reconciliation-discovered change, the Connector runs the entity's `canonicalize(entity_type, raw_data) -> dict` function (per ADR-0003) and computes its Fingerprint. If this matches the stored Fingerprint for that system/Synced Entity, the change is an Echo of the Connector's own prior write and is discarded without further processing. Otherwise, it's a genuine change and is queued for sync to the other system; after a successful write, the Connector recomputes and stores fresh Fingerprints for both sides.

### Trigger model & reconciliation

- Real-time: Shopify webhook subscriptions (`webhookSubscriptionCreate`) for product, inventory, order, fulfillment, and customer events; Frappe Webhooks on the ERPNext side for the corresponding doctypes.
- Backstop: an APScheduler job runs on a recurring schedule, using Shopify Bulk Operations (`bulkOperationRunQuery`) and ERPNext list queries to walk all Synced Entities, recompute Fingerprints, and enqueue syncs for anything that drifted without a webhook firing.

### Failure handling

- Every outbound write goes through the persistent retry queue. Failures are retried with exponential backoff.
- After a configured number of attempts, an item moves to `dead_letter` with `last_error` recorded, for manual investigation — it is not silently dropped, and the next reconciliation pass will independently re-derive and re-enqueue the underlying change if it's still outstanding.

### Tech stack (per ADR-0002)

Python, FastAPI (webhook receiver + status API), SQLModel + SQLite (Synced Entity / Fingerprint / retry queue store), APScheduler (reconciliation), `httpx` + hand-written Pydantic models for Shopify GraphQL requests/responses, `frappeclient` for ERPNext REST.

### Local development

The Connector runs locally for this phase (per the deployment-infra decision). Since Shopify delivers webhooks over the public internet, local development requires a tunnel (e.g. ngrok or a Cloudflare Tunnel) pointed at the Connector's webhook-receiver endpoints.

## Testing Decisions

A good test in this codebase asserts on **external behavior** — the calls made to the *other* system's client, and the resulting Synced Entity/Fingerprint/retry-queue state — not on internal call sequences or private helper functions.

- **Canonicalization & Fingerprint functions** (`canonicalize(entity_type, raw_data) -> dict` and the Fingerprint computed from it, per ADR-0003): pure unit tests, no I/O. Given representative Shopify GraphQL response fragments and ERPNext REST response fragments for each `entity_type`, assert the canonical form and resulting Fingerprint. Critically, assert that changes to *untracked* fields (e.g. `updatedAt`/`modified` timestamps, permission metadata) produce the **same** Fingerprint, while changes to *tracked* fields produce a **different** one — this is the property ADR-0003 calls safety-critical.

- **Sync handler functions** (one per direction per `entity_type` — e.g. "Shopify product changed → ERPNext Item", "ERPNext Sales Order submitted → Shopify Order"): the primary seam, covering nearly all user stories above. Tested against `ShopifyClient` and `ERPNextClient` Protocol interfaces with in-memory fake implementations, and a real SQLite-backed Synced Entity/retry-queue store (temp file or `:memory:`). Given an inbound payload and a starting Synced Entity/Fingerprint state, assert: (a) the calls made to the fake client for the *other* system, (b) the resulting Synced Entity and Fingerprint rows, and (c) Echo cases produce *no* calls to the other system's client.

- **Webhook/HTTP layer**: FastAPI `TestClient` against the webhook-receiver endpoints. Verify HMAC signature validation (valid, invalid, and missing signature) and correct routing to the corresponding sync handler, with the handler faked.

- **Retry queue**: pure logic tests over queue-row state transitions — `pending → retry (with backoff)`, and `retry → dead_letter` after the configured attempt limit.

- **Prior art**: none — this is a greenfield codebase, so these patterns establish the baseline for everything built afterward.

- **Manual end-to-end pass**: a scripted but manually-run pass against a real Shopify development store and ERPNext sandbox, using representative test records covering each entity type and direction in this PRD. This satisfies the hiring challenge's "data validation with test records" deliverable and is run separately from the automated suite (it's slow, depends on live external state, and isn't suitable for CI).

## Out of Scope

- ERPNext version research, selection, and deployment (a separate workstream/task in the broader hiring challenge — this PRD assumes a running, reachable ERPNext instance with REST API access and permission to add Custom Fields and Webhooks).
- Bonus integrations beyond Shopify ↔ ERPNext.
- Public/production deployment, hosting, and TLS termination for the Connector (current decision: local/dev environment, no public endpoint).
- Multi-location/multi-warehouse inventory mapping — only a single configured Location↔Warehouse pair.
- Multi-currency support.
- Shopify draft orders, abandoned checkouts, and B2B/wholesale-specific objects.
- Detailed Shopify tax-line ↔ ERPNext Sales Taxes and Charges *template* mapping beyond carrying the resulting totals onto the Sales Invoice (flagged in Further Notes for follow-up once real order payloads are available).
- An admin dashboard/UI — operational visibility is via the status API only (user story 38).

## Further Notes

- The three existing ADRs are binding context for implementation and should be read first: `docs/adr/0001-shopify-graphql-admin-api.md`, `docs/adr/0002-python-fastapi-connector.md`, `docs/adr/0003-fingerprint-as-content-hash.md`.
- `CONTEXT.md` defines the project's vocabulary (Connector, Synced Entity, Fingerprint, Echo, Order, Fulfillment) — use these terms, and the terms each entry says to avoid, throughout implementation, tests, and any further design discussion.
- Tax/shipping/discount fidelity on Sales Invoices (see Out of Scope) should be revisited once real Shopify order payloads are available from the development store, to confirm whether ERPNext's existing Sales Taxes and Charges templates can represent them without per-order manual configuration — this may warrant its own follow-up PRD or ADR.
- ERPNext version selection and the broader 12-month integration strategy/assessment (also part of the hiring challenge) are intentionally not addressed here and should be tracked separately.
