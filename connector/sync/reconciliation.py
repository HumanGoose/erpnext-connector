"""Recurring reconciliation pass (issue 14).

A generic, scheduled backstop: walks every Synced Entity row, re-fetches
current data for each side, recomputes both Fingerprints via the
`CANONICALIZERS` registry (per ADR-0003), and enqueues a retry-queue entry for
either side whose recomputed Fingerprint has drifted from the stored one —
identical in shape to what the corresponding webhook handler would enqueue.

Generic over `entity_type`: adding a new `canonicalize` registration to
`connector.fingerprint.CANONICALIZERS` is enough for this pass to start
covering it, with no changes here.
"""

import json
from typing import Any

from sqlmodel import Session, select

from connector import retry_queue
from connector.config import get_settings
from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import CANONICALIZERS, fingerprint
from connector.models import EntityType, SyncDirection, SyncedEntity
from connector.shopify.client import ShopifyClientProtocol


def run_reconciliation(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
) -> int:
    """Walk all Synced Entity rows; enqueue a retry-queue entry for any row
    whose recomputed Fingerprint drifted on either side. Returns the number of
    entries enqueued."""
    enqueued = 0
    for entity in session.exec(select(SyncedEntity)).all():
        canonicalizer = CANONICALIZERS.get(entity.entity_type)
        if canonicalizer is None:
            continue  # No registered canonicalizer for this entity_type yet.

        shopify_raw = _fetch_shopify(shopify_client, entity)
        erpnext_raw = _fetch_erpnext(erpnext_client, entity)
        if shopify_raw is None and erpnext_raw is None:
            continue

        if shopify_raw is not None:
            new_shopify_fp = fingerprint(canonicalizer(shopify_raw))
            if new_shopify_fp != entity.shopify_fingerprint:
                _enqueue_drift(session, entity, SyncDirection.SHOPIFY_TO_ERPNEXT, shopify_raw)
                enqueued += 1

        if erpnext_raw is not None:
            new_erpnext_fp = fingerprint(canonicalizer(erpnext_raw))
            if new_erpnext_fp != entity.erpnext_fingerprint:
                _enqueue_drift(session, entity, SyncDirection.ERPNEXT_TO_SHOPIFY, erpnext_raw)
                enqueued += 1

    return enqueued


def _enqueue_drift(session: Session, entity: SyncedEntity, direction: SyncDirection, raw: dict[str, Any]) -> None:
    retry_queue.enqueue(
        session,
        direction=direction,
        entity_type=entity.entity_type,
        payload=json.dumps(raw),
        synced_entity_id=entity.id,
    )


def _fetch_shopify(shopify_client: ShopifyClientProtocol, entity: SyncedEntity) -> dict[str, Any] | None:
    if entity.shopify_gid is None:
        return None
    fetcher = getattr(shopify_client, "fetch_for_reconciliation", None)
    if fetcher is None:
        return None
    return fetcher(entity.entity_type, entity.shopify_gid)


def _fetch_erpnext(erpnext_client: ERPNextClientProtocol, entity: SyncedEntity) -> dict[str, Any] | None:
    if entity.erpnext_doctype is None or entity.erpnext_name is None:
        return None

    if entity.entity_type == EntityType.INVENTORY_LEVEL:
        settings = get_settings()
        bins = erpnext_client.get_list(
            "Bin",
            filters={"item_code": entity.erpnext_name, "warehouse": settings.erpnext_warehouse},
            fields=["actual_qty"],
        )
        available = int(bins[0]["actual_qty"]) if bins else 0
        return {"available": available}

    try:
        return erpnext_client.get_doc(entity.erpnext_doctype, entity.erpnext_name)
    except LookupError:
        return None
