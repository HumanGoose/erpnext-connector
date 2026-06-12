"""Inventory sync in both directions (issues 12, 13).

Both directions normalize a stock change to "set the absolute available
quantity to N" for the single configured Shopify Location <-> ERPNext Warehouse
pair (per PRD). Inventory state is tracked as its own `inventory_level` Synced
Entity (one per variant), so an Echo of the Connector's own write is recognized
independently of the product/variant Fingerprints.
"""

from typing import Any

from sqlmodel import Session

from connector.config import get_settings
from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncedEntity
from connector.shopify.client import ShopifyClientProtocol
from connector.sync import entities


def _inventory_entity(session: Session, item_code: str) -> SyncedEntity | None:
    return entities.get_by_erpnext(session, EntityType.INVENTORY_LEVEL, "Item", item_code)


def _variant_gid_for(session: Session, item_code: str) -> str | None:
    variant = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", item_code)
    if variant is not None:
        return variant.shopify_gid
    product = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item_code)
    return product.shopify_gid if product is not None else None


def handle_stock_webhook(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """ERPNext stock change -> Shopify inventory (issue 12).

    `payload` carries the affected `item_code` (and optionally `warehouse`);
    the absolute quantity is read from ERPNext's Bin for the configured
    Warehouse. Items/Warehouses outside the configured pairing are ignored."""
    settings = get_settings()
    item_code = payload.get("item_code")
    if not item_code:
        return
    warehouse = payload.get("warehouse")
    if warehouse is not None and warehouse != settings.erpnext_warehouse:
        return  # A different Warehouse — out of scope for this phase.

    item = erpnext_client.get_doc("Item", item_code)
    inventory_item_gid = item.get("shopify_inventory_item_gid")
    if not inventory_item_gid:
        return  # Not synced to a Shopify inventory item.

    quantity = _erpnext_quantity(erpnext_client, item_code, settings.erpnext_warehouse)
    canonical = canonicalize(EntityType.INVENTORY_LEVEL, {"available": quantity})
    fp = fingerprint(canonical)

    entity = _inventory_entity(session, item_code)
    if entity is not None and entity.erpnext_fingerprint == fp:
        return  # Echo: quantity unchanged (e.g. our own write from issue 13).

    shopify_client.set_inventory_quantity(inventory_item_gid, settings.shopify_location_gid, quantity)

    entities.save(
        session,
        entity,
        entity_type=EntityType.INVENTORY_LEVEL,
        shopify_gid=inventory_item_gid,
        group_key=_variant_gid_for(session, item_code),
        erpnext_doctype="Item",
        erpnext_name=item_code,
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )


def _erpnext_quantity(erpnext_client: ERPNextClientProtocol, item_code: str, warehouse: str) -> int:
    bins = erpnext_client.get_list(
        "Bin",
        filters={"item_code": item_code, "warehouse": warehouse},
        fields=["actual_qty"],
    )
    if not bins:
        return 0
    return int(bins[0].get("actual_qty") or 0)


def handle_shopify_inventory_webhook(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Shopify inventory change -> ERPNext Stock Reconciliation (issue 13).

    Applies to the configured Location only; the new absolute quantity is
    written to ERPNext via a submitted Stock Reconciliation."""
    settings = get_settings()
    location_gid = _gid(payload.get("location_id"), "Location")
    if location_gid != settings.shopify_location_gid:
        return  # Inventory at a non-configured Location — ignored.

    inventory_item_gid = _gid(payload.get("inventory_item_id"), "InventoryItem")
    entity = entities.get_by_shopify_gid(session, EntityType.INVENTORY_LEVEL, inventory_item_gid)
    if entity is None:
        return  # No Synced Entity for this inventory item.

    quantity = int(payload.get("available") or 0)
    canonical = canonicalize(EntityType.INVENTORY_LEVEL, {"available": quantity})
    fp = fingerprint(canonical)
    if entity.shopify_fingerprint == fp:
        return  # Echo: our own write from issue 12.

    item_code = entity.erpnext_name
    recon = {
        "doctype": "Stock Reconciliation",
        "purpose": "Stock Reconciliation",
        "items": [
            {
                "item_code": item_code,
                "warehouse": settings.erpnext_warehouse,
                "qty": quantity,
            }
        ],
    }
    created = erpnext_client.insert(recon)
    erpnext_client.submit(created)

    entity.shopify_fingerprint = fp
    entity.erpnext_fingerprint = fp
    entities.save(session, entity)


def _gid(raw_id: Any, resource: str) -> str:
    if raw_id is None:
        return ""
    if isinstance(raw_id, str) and raw_id.startswith("gid://"):
        return raw_id
    return f"gid://shopify/{resource}/{raw_id}"
