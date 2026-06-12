# Shopify product/variant → ERPNext Item sync (create/update)

Status: ready-for-agent

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers user stories 1, 2, 3, 5, and establishes Echo detection (story 34) for the first time.

## What to build

Implement the first instance of the canonicalize/Fingerprint framework (per ADR-0003): a `canonicalize(entity_type, raw_data) -> dict` function for `entity_type="product"` and `"variant"` that extracts only the tracked fields (title, description, options/variant attributes, SKUs — pricing and image fields are added by later issues 08/10) from either a Shopify GraphQL payload or an ERPNext Item REST response, plus a Fingerprint function (SHA256 of the canonical JSON).

Wire a webhook receiver endpoint for Shopify `products/create` and `products/update` topics (HMAC-verified via issue 02's helper), routing to a sync handler that:

- Checks the incoming product's Fingerprint against the stored `shopify_fingerprint` for its Synced Entity — an Echo (per story 34) is discarded without further processing.
- For a genuine change, creates or updates the corresponding ERPNext template Item (`has_variants=1`, one Item Attribute per Shopify product `option`) and one ERPNext variant Item per Shopify ProductVariant (`variant_of=<template item code>`, attribute values from `selectedOptions`), using SKU as the initial join key and storing `shopify_product_gid`/`shopify_variant_gid` Custom Fields on first sync. A Shopify product with only its single default variant maps to one non-variant ERPNext Item.
- Records/updates the Synced Entity row(s) and both Fingerprints after a successful write.
- New variants added to an existing synced product create new ERPNext variant Items under the existing template.

## Acceptance criteria

- [x] `canonicalize("product"/"variant", raw_data)` and the Fingerprint function are pure, unit-tested functions producing identical output regardless of whether `raw_data` came from a webhook payload or a GraphQL query, per ADR-0003.
- [x] Unit tests assert that changes to untracked fields (e.g. `updatedAt`) do not change the Fingerprint, while changes to tracked fields (title, description, options, SKUs) do.
- [x] A FastAPI webhook-receiver endpoint accepts `products/create` and `products/update`, validates HMAC (rejecting invalid/missing signatures), and routes to the sync handler.
- [x] The sync handler performs Echo detection: if the computed Fingerprint matches the stored `shopify_fingerprint`, no calls are made to `ERPNextClient` (tested with fakes).
- [x] For a genuine new product: the handler creates an ERPNext template Item with the right Item Attributes and variant Items (or a single non-variant Item for single-variant products), and creates Synced Entity rows with both Fingerprints populated — asserted against a fake `ERPNextClient` and a real SQLite-backed Synced Entity store.
- [x] For a genuine update (title/description change): the handler updates the existing ERPNext Item(s) and refreshes both Fingerprints.
- [x] Adding a new variant to an already-synced product creates a new ERPNext variant Item under the existing template and a new Synced Entity row for it.

## Blocked by

- 02-shopify-graphql-client.md
- 03-erpnext-client-and-setup.md
- 04-retry-queue-and-status-api.md

## Comments

- Implemented: `connector/fingerprint.py` (`canonicalize`/`fingerprint` for `EntityType.PRODUCT`/`VARIANT`, normalizing webhook (`body_html`, `option1/2/3`) and GraphQL (`descriptionHtml`, `selectedOptions`) shapes to the same canonical dict), `connector/sync/products.py` (`handle_product_webhook`, with per-part Echo detection against `shopify_fingerprint` for the template and each variant independently; "simple" single-default-variant products map to one non-variant Item carrying both `shopify_product_gid`/`shopify_variant_gid`), `connector/api/shopify_webhooks.py` (`POST /webhooks/shopify/products`, HMAC-verified via issue 02's `verify_webhook_hmac`), `connector/erpnext/client.py` (added `get_erpnext_client` FastAPI dependency). Tests in `tests/test_fingerprint.py` (13), `tests/sync/test_products.py` (6), `tests/api/test_shopify_webhooks.py` (5). `pytest -q` passes (58 passed total).
