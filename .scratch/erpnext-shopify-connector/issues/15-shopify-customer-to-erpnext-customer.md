# Shopify customer → ERPNext Customer sync

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 19, 20.

## What to build

Implement `canonicalize("customer", ...)` tracking name, email, phone, and addresses for either a Shopify Customer GraphQL payload or an ERPNext Customer REST response, plus its Fingerprint.

Wire a webhook receiver for Shopify customer create/update topics (HMAC-verified). The sync handler:

- Performs Echo detection against `shopify_fingerprint`.
- On a genuine change, creates or updates the corresponding ERPNext Customer (storing `shopify_customer_gid` on first sync) and the Synced Entity row with refreshed Fingerprints.

## Acceptance criteria

- [x] `canonicalize("customer", ...)` tracks name, email, phone, and addresses; Fingerprint is stable under untracked-field changes and changes when any tracked field changes.
- [x] Webhook receiver routes Shopify customer create/update events (HMAC-verified) to the sync handler.
- [x] Echo detection: a customer change matching the stored `shopify_fingerprint` results in no `ERPNextClient` calls.
- [x] A genuine new customer creates an ERPNext Customer with `shopify_customer_gid` set and a new Synced Entity row with both Fingerprints.
- [x] A genuine update to name/email/phone/address updates the existing ERPNext Customer and refreshes both Fingerprints.

## Blocked by

- 02-shopify-graphql-client.md
- 03-erpnext-client-and-setup.md
- 04-retry-queue-and-status-api.md

## Comments

- Implemented: `connector/fingerprint.py` (`_canonicalize_customer` for `EntityType.CUSTOMER`, tracking name/email/phone/addresses across Shopify webhook and ERPNext REST shapes), `connector/sync/customers.py::handle_shopify_customer_webhook` (Echo detection against `shopify_fingerprint`, denormalizes addresses onto the ERPNext Customer doc per the module docstring), `connector/api/shopify_webhooks.py` (`POST /webhooks/shopify/customers`, HMAC-verified, routes `customers/create`/`customers/update`). Tests in `tests/sync/test_customers.py` (3) and `tests/api/test_shopify_sync_webhooks.py` (topic routing). `pytest -q` passes (99 passed total).
