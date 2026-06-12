# Fingerprints are content hashes, not timestamps

The simpler alternative for detecting Echoes is comparing `updatedAt` (Shopify) / `modified` (Frappe) timestamps against the last value seen by the Connector. But both systems bump these timestamps on saves that don't touch any field the Connector actually tracks — e.g. Frappe updates `modified` on workflow/permission-only changes, and Shopify can recompute `updatedAt` for unrelated reasons. Timestamp comparison would misclassify these as genuine changes, defeating Echo detection.

A Fingerprint is therefore a SHA256 hash of a canonical JSON object containing only the fields this project tracks for a given `entity_type` (e.g. for `product`: title, description, variant prices, image URLs, inventory qty). Each entity type has a `canonicalize(entity_type, raw_data) -> dict` function, applied identically whether the data came from a webhook payload, a GraphQL query, or a Frappe REST response.

## Consequences

- Adding a newly-tracked field to an entity type changes its canonical form, which changes all future Fingerprints for that type — existing stored Fingerprints become stale and the next sync pass will (correctly, but once) treat every entity of that type as changed.
- The canonicalization step must be carefully kept in sync between the "data we just wrote" path and the "data we just received" path, or Fingerprints will never match and Echo detection will silently fail (every write becomes an infinite loop). This is the most safety-critical piece of code in the Connector and should be unit-tested directly.
