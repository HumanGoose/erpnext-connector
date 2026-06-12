# Shopify GraphQL client: rate limiting, HMAC verification, webhook subscription registration

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user story 40.

## What to build

Build the Connector's Shopify-side client exclusively on the GraphQL Admin API (per ADR-0001), using `httpx` with hand-written Pydantic models (per ADR-0002).

- Implement cost-based rate limiting by reading `extensions.cost.throttleStatus` from GraphQL responses and pacing/backing off subsequent requests accordingly — not a per-second call-count bucket.
- Implement HMAC-SHA256 verification of inbound Shopify webhook payloads against the configured webhook secret.
- Implement a routine that registers the Connector's required Shopify webhook subscriptions via `webhookSubscriptionCreate` for product, inventory, order, fulfillment, and customer topics, pointing at the Connector's webhook-receiver endpoints.

## Acceptance criteria

- [ ] A `ShopifyClient` wraps `httpx` calls to the GraphQL Admin API, exposing typed (Pydantic) request/response models for the queries/mutations this issue needs.
- [ ] The client tracks `extensions.cost.throttleStatus` from each response and paces/delays subsequent requests to avoid exceeding the bucket, with a unit test simulating a throttled response.
- [ ] An HMAC verification helper validates the `X-Shopify-Hmac-SHA256` header against the configured secret, with tests for valid, invalid, and missing-signature cases.
- [ ] A setup routine calls `webhookSubscriptionCreate` to register subscriptions for product, inventory, order, fulfillment, and customer topics against the Connector's webhook-receiver base URL, idempotently (re-running it doesn't create duplicate subscriptions).
- [ ] Tests use a fake/mock HTTP transport — no live calls to a real Shopify store are required to pass the suite.

## Blocked by

- 01-connector-scaffolding.md

## Comments

- Implemented: `connector/shopify/models.py` (Pydantic models for the GraphQL envelope incl. `extensions.cost.throttleStatus`, and `webhookSubscriptions`/`webhookSubscriptionCreate` shapes), `connector/shopify/client.py` (`ShopifyClient` over `httpx.Client`, cost-based pacing via `_wait_for_capacity`, `ShopifyGraphQLError`), `connector/shopify/webhooks.py` (`verify_webhook_hmac` + `WEBHOOK_TOPICS` topic->path map covering products/inventory/orders/fulfillments/customers/refunds), `connector/shopify/setup.py` (`register_webhook_subscriptions`, idempotent via a `webhookSubscriptions` listing query, plus a `main()` CLI entrypoint). Added `CONNECTOR_BASE_URL` to config/`.env.example` for the webhook callback base. Tests in `tests/shopify/` use `httpx.MockTransport` (no live Shopify calls): rate-limit pacing (`test_client.py`), HMAC valid/invalid/tampered/missing (`test_webhooks.py`), and idempotent registration across two passes (`test_setup.py`). `pytest -q` passes (13 passed total).
