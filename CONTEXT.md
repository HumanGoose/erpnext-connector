# ERPNext ↔ Shopify Connector

A standalone service that keeps product, inventory, order, and customer data synchronized in both directions between Shopify and ERPNext, without modifying either system's core behavior.

## Language

**Connector**:
The standalone middleware service that performs synchronization. ERPNext and Shopify remain stock/unmodified systems (aside from a small number of Custom Fields and Webhook configurations on the ERPNext side).
_Avoid_: Integration, middleware, sync service, bridge

**Synced Entity**:
A pairing of one record in Shopify and one record in ERPNext that represent the same real-world object (e.g. a product, an order, a customer). The Connector tracks this pairing.
_Avoid_: Mapping, linked record, paired record

**Fingerprint**:
A snapshot (hash or version marker) of a Synced Entity's data in a given system, taken by the Connector immediately after it writes to that system. Used to recognize Echoes.
_Avoid_: Checksum, version, snapshot, hash

**Echo**:
An inbound change notification that reflects the Connector's own prior write rather than a genuine new edit by a user. Detected by comparing incoming data against the stored Fingerprint, and discarded without further processing.
_Avoid_: Loop, duplicate event, self-trigger, feedback loop

## Orders

**Order** (as a Synced Entity):
A Shopify Order paired with its corresponding ERPNext document set: a Sales Order, a Sales Invoice, and a Payment Entry (all created together when the Shopify order arrives, since Shopify orders are pre-paid), plus a Delivery Note once shipped.
_Avoid_: Transaction, sale

**Fulfillment**:
The shipping of an order's items, represented in ERPNext by a submitted Delivery Note and in Shopify by a fulfillment record (created via `fulfillmentCreate`). Fulfillment is the specific signal that flows bidirectionally between the two systems for "order status."
_Avoid_: Shipment, dispatch (use these only when referring to the physical act, not the synced record)
