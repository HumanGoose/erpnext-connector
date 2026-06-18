"""Inventory sync in both directions (issues 12, 13).

Both directions normalize a stock change to "set the absolute available
quantity to N" for the single configured Shopify Location <-> ERPNext Warehouse
pair (per PRD). Inventory state is tracked as its own `inventory_level` Synced
Entity (one per variant), so an Echo of the Connector's own write is recognized
independently of the product/variant Fingerprints.
"""

from datetime import date
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


def seed_inventory_entity(
    session: Session,
    inventory_item_gid: str,
    group_key: str,
    item_code: str,
) -> None:
    """Create or refresh the INVENTORY_LEVEL SyncedEntity for an item.

    Fingerprints are left empty — they're filled on the first actual inventory
    sync. Called from both the Shopify→ERPNext and ERPNext→Shopify product sync
    paths so the entity exists before any stock webhook fires.
    """
    entity = _inventory_entity(session, item_code)
    entities.save(
        session,
        entity,
        entity_type=EntityType.INVENTORY_LEVEL,
        shopify_gid=inventory_item_gid,
        group_key=group_key,
        erpnext_doctype="Item",
        erpnext_name=item_code,
    )


def push_item_inventory(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    item_code: str,
) -> None:
    """Push the current ERPNext bin quantity to Shopify immediately.

    Used as an initial sync after a product/variant is first created in Shopify
    from ERPNext so the opening stock is reflected right away. No-op when
    SHOPIFY_LOCATION_GID is still the placeholder value.
    """
    settings = get_settings()
    if settings.shopify_location_gid in ("", "gid://shopify/Location/00000000"):
        return
    _sync_item_inventory(session, shopify_client, erpnext_client, settings, item_code)


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

    Stock Entry and Stock Reconciliation both carry affected items in a child
    table (`payload["items"]`), not at the top level. Each item's absolute
    quantity is read from ERPNext's Bin for the configured Warehouse.
    Items/Warehouses outside the configured pairing are ignored."""
    settings = get_settings()
    stock_items = payload.get("items") or []
    seen: set[str] = set()
    for stock_item in stock_items:
        item_code = stock_item.get("item_code")
        if not item_code or item_code in seen:
            continue
        # Stock Entry: s_warehouse (source) / t_warehouse (target).
        # Stock Reconciliation: warehouse.
        warehouses = {
            stock_item.get("warehouse"),
            stock_item.get("s_warehouse"),
            stock_item.get("t_warehouse"),
        } - {None, ""}
        if warehouses and settings.erpnext_warehouse not in warehouses:
            continue
        seen.add(item_code)
        _sync_item_inventory(session, shopify_client, erpnext_client, settings, item_code)


def _sync_item_inventory(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    settings: Any,
    item_code: str,
) -> None:
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

    # Preserve the existing group_key when updating — it was set correctly by
    # seed_inventory_entity (to the product GID) and must not be overwritten
    # with None when _variant_gid_for cannot resolve the entity yet (e.g. on
    # first-sync when the VARIANT entity hasn't been saved yet).
    group_key = (entity.group_key if entity is not None else None) or _variant_gid_for(session, item_code)
    entities.save(
        session,
        entity,
        entity_type=EntityType.INVENTORY_LEVEL,
        shopify_gid=inventory_item_gid,
        group_key=group_key,
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


def _valuation_rate(erpnext_client: ERPNextClientProtocol, item_code: str, warehouse: str) -> float:
    bins = erpnext_client.get_list(
        "Bin",
        filters={"item_code": item_code, "warehouse": warehouse},
        fields=["valuation_rate"],
    )
    if bins and bins[0].get("valuation_rate"):
        return float(bins[0]["valuation_rate"])
    item = erpnext_client.get_doc("Item", item_code)
    rate = item.get("valuation_rate") or item.get("standard_rate") or item.get("last_purchase_rate")
    if rate:
        return float(rate)
    prices = erpnext_client.get_list(
        "Item Price",
        filters={"item_code": item_code},
        fields=["price_list_rate"],
        limit_page_length=1,
    )
    if prices and prices[0].get("price_list_rate"):
        return float(prices[0]["price_list_rate"])
    return 1.0


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
    valuation = _valuation_rate(erpnext_client, item_code, settings.erpnext_warehouse)
    recon: dict[str, Any] = {
        "doctype": "Stock Reconciliation",
        "posting_date": date.today().isoformat(),
        "purpose": "Stock Reconciliation",
        "items": [
            {
                "item_code": item_code,
                "warehouse": settings.erpnext_warehouse,
                "qty": quantity,
                "valuation_rate": valuation,
            }
        ],
    }
    # On a fresh ERPNext with no prior stock transactions, ERPNext treats
    # Stock Reconciliation as an "Opening Entry" and requires the expense
    # account to be a Balance Sheet (Asset/Liability) type rather than P&L.
    # Always pass the company's Temporary Opening account to satisfy this
    # requirement — it is acceptable for both opening and regular entries.
    opening_account = _temporary_opening_account(erpnext_client)
    if opening_account:
        recon["expense_account"] = opening_account
    created = erpnext_client.insert(recon)
    erpnext_client.submit(created)

    entity.shopify_fingerprint = fp
    entity.erpnext_fingerprint = fp
    entities.save(session, entity)


def _temporary_opening_account(erpnext_client: ERPNextClientProtocol) -> str:
    """Return the Temporary Opening account for this ERPNext company.

    ERPNext rejects a Stock Reconciliation expense_account that is a P&L
    type when it considers the entry an "Opening Entry" (no prior stock
    transactions exist). The Temporary Opening account is a Balance Sheet
    account that is always valid as the expense_account for reconciliations.
    """
    try:
        # get_list doesn't expose company-account fields; use get_doc instead.
        names = erpnext_client.get_list("Company", filters={}, fields=["name", "abbr"])
        if not names:
            return ""
        company = erpnext_client.get_doc("Company", names[0]["name"])
        return (
            company.get("temporary_opening")
            or f"Temporary Opening - {names[0].get('abbr', '')}"
        )
    except Exception:
        return ""


def _gid(raw_id: Any, resource: str) -> str:
    if raw_id is None:
        return ""
    if isinstance(raw_id, str) and raw_id.startswith("gid://"):
        return raw_id
    return f"gid://shopify/{resource}/{raw_id}"
