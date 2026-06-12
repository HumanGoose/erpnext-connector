# Use Shopify GraphQL Admin API instead of REST Admin API

Shopify marked the REST Admin API as legacy as of October 1, 2024. New public apps must use the GraphQL Admin API exclusively (enforced since April 1, 2025), and custom apps using REST/legacy GraphQL fields for Products and Variants had a migration deadline of April 1, 2025 — already past as of this project's start. Building a new connector on REST in 2026 means building on an API surface Shopify has stopped extending, especially for the Product/Variant endpoints this project depends on most.

We will build the Connector's Shopify-side client exclusively on the GraphQL Admin API: webhook subscriptions via `webhookSubscriptionCreate`, catalog/order/customer reads via GraphQL queries, the reconciliation poll via Bulk Operations (`bulkOperationRunQuery`), and order creation (Phase 2) via `orderCreate`.

## Considered Options

- **REST Admin API** — simpler request/pagination model, more existing tutorials and community connector code to learn from, but legacy/frozen and already past its migration deadline for the Product/Variant endpoints.

## Consequences

- The Connector must implement GraphQL's cost-based rate limiting (reading `extensions.cost.throttleStatus` and pacing requests), not REST's simple per-second call-count bucket.
- Pagination is cursor-based (`edges`/`pageInfo`) throughout.
- `orderCreate` requires the `write_orders` scope, an offline access token, and (as of API version 2026-04) an idempotency key via the `@idempotent` directive. It's explicitly documented for "importing orders from an external system or creating orders for wholesale customers" — directly our Phase 2 use case, which lowers the risk previously flagged for that phase.
