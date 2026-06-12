# Manual end-to-end validation pass (real Shopify dev store + ERPNext sandbox)

Status: ready-for-human

## Parent

`.scratch/erpnext-shopify-connector/PRD.md` — covers the "Manual end-to-end pass" testing decision (the hiring challenge's "data validation with test records" deliverable).

## What to build

Per the PRD's Testing Decisions, produce a scripted but manually-run validation pass against a real Shopify development store and an ERPNext sandbox, using representative test records covering each entity type (product/variant, image, price, inventory, customer, order, fulfillment, cancellation/refund) and both sync directions.

This requires a human to:

- Stand up the Shopify development store and ERPNext sandbox, with the Connector's setup routines (issues 02/03) run against them.
- Expose the Connector's webhook-receiver endpoints to the public internet via a tunnel (e.g. ngrok or a Cloudflare Tunnel), per the PRD's Local Development notes.
- Run the scripted scenarios and record/validate the observed outcomes in both systems.

## Acceptance criteria

- [ ] A documented, runnable script (or set of scripts) exercises representative test records for each entity type and direction covered by issues 05–23.
- [ ] The Connector's webhook-receiver endpoints are reachable from the public internet via a tunnel pointed at the local Connector instance.
- [ ] For each scenario, the resulting state in both Shopify and ERPNext is recorded and confirmed to match expectations (e.g. correct Item/variant created, correct Sales Order/Invoice/Payment Entry totals, correct Fulfillment/Delivery Note status, correct cancellation/refund records).
- [ ] Echo behavior is spot-checked: a Connector-originated write does not trigger a redundant reverse sync.
- [ ] Results are written up (e.g. under `.scratch/erpnext-shopify-connector/`) as the validation deliverable, noting any discrepancies found and whether they were fixed or filed as follow-up issues.

## Blocked by

- 05-shopify-product-to-erpnext-item.md
- 06-shopify-product-archive-to-item-disable.md
- 07-erpnext-item-to-shopify-product.md
- 08-shopify-images-to-erpnext-item.md
- 09-erpnext-item-images-to-shopify.md
- 10-shopify-price-to-erpnext-item-price.md
- 11-erpnext-item-price-to-shopify.md
- 12-erpnext-stock-to-shopify-inventory.md
- 13-shopify-inventory-to-erpnext-stock-reconciliation.md
- 14-recurring-reconciliation-pass.md
- 15-shopify-customer-to-erpnext-customer.md
- 16-erpnext-customer-to-shopify-customer.md
- 17-shopify-order-to-erpnext-so-si-pe.md
- 18-erpnext-sales-order-to-shopify-order.md
- 19-erpnext-delivery-note-to-shopify-fulfillment.md
- 20-shopify-fulfillment-to-erpnext-delivery-note.md
- 21-shopify-order-cancellation-cascade.md
- 22-erpnext-sales-order-cancellation-to-shopify.md
- 23-shopify-refund-to-erpnext-credit-note.md
