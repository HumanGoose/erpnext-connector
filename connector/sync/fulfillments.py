"""Fulfillment sync in both directions (issues 19, 20).

Fulfillment is the bidirectional order-status signal: an ERPNext submitted
Delivery Note <-> a Shopify fulfillment record. Tracked as its own
`fulfillment` Synced Entity (grouped with its Order), whose canonical form is
the set of fulfilled (variant, quantity) lines — so partial fulfillment and
Echo detection both fall out of the Fingerprint.
"""

from typing import Any

from sqlmodel import Session

from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncedEntity
from connector.shopify.client import ShopifyClientProtocol
from connector.sync import entities


def _variant_gid(line: dict[str, Any]) -> str:
    if line.get("variant_gid"):
        return line["variant_gid"]
    variant = line.get("variant") or {}
    if variant.get("id"):
        return variant["id"]
    return f"gid://shopify/ProductVariant/{line.get('variant_id')}"


def _order_entity_for_so(session: Session, sales_order: str) -> SyncedEntity | None:
    return entities.get_by_erpnext(session, EntityType.ORDER, "Sales Order", sales_order)


def _fulfillment_entity(session: Session, order_gid: str) -> SyncedEntity | None:
    group = entities.get_group(session, order_gid, EntityType.FULFILLMENT)
    return group[0] if group else None


# --- Issue 19: ERPNext Delivery Note -> Shopify fulfillmentCreate ---


def handle_delivery_note_submit(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    sales_order = payload.get("against_sales_order") or _items_sales_order(payload)
    if not sales_order:
        return
    order_entity = _order_entity_for_so(session, sales_order)
    if order_entity is None or order_entity.shopify_gid is None:
        return
    order_gid = order_entity.shopify_gid

    # Map Delivery Note lines to Shopify variants via the variant Synced Entities.
    fulfilled_lines = []
    for row in payload.get("items") or []:
        variant_entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", row["item_code"])
        if variant_entity is None:
            variant_entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", row["item_code"])
        if variant_entity is None or variant_entity.shopify_gid is None:
            continue
        fulfilled_lines.append(
            {"variant_gid": variant_entity.shopify_gid, "quantity": int(row.get("qty") or 0)}
        )

    canonical = canonicalize(EntityType.FULFILLMENT, {"line_items": fulfilled_lines})
    fp = fingerprint(canonical)

    entity = _fulfillment_entity(session, order_gid)
    if entity is not None and entity.erpnext_fingerprint == fp:
        return  # Echo: this fulfillment state is already recorded.

    fulfillment_input = {
        "orderId": order_gid,
        "lineItems": [
            {"variantId": line["variant_gid"], "quantity": line["quantity"]} for line in fulfilled_lines
        ],
    }
    fulfillment = shopify_client.create_fulfillment(fulfillment_input)
    fulfillment_gid = fulfillment["id"]

    erpnext_client.set_value("Delivery Note", payload["name"], "shopify_fulfillment_gid", fulfillment_gid)

    entities.save(
        session,
        entity,
        entity_type=EntityType.FULFILLMENT,
        shopify_gid=fulfillment_gid,
        group_key=order_gid,
        erpnext_doctype="Delivery Note",
        erpnext_name=payload["name"],
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )


def _items_sales_order(payload: dict[str, Any]) -> str | None:
    for row in payload.get("items") or []:
        if row.get("against_sales_order"):
            return row["against_sales_order"]
    return None


# --- Issue 20: Shopify fulfillment -> ERPNext Delivery Note ---


def handle_shopify_fulfillment_webhook(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    order_gid = _fulfillment_order_gid(payload)
    order_entity = entities.get_by_shopify_gid(session, EntityType.ORDER, order_gid)
    if order_entity is None or order_entity.erpnext_name is None:
        return
    sales_order = order_entity.erpnext_name

    fulfilled_lines = []
    dn_items = []
    for line in payload.get("line_items") or []:
        variant_gid = _variant_gid(line)
        variant_entity = entities.get_by_shopify_gid(session, EntityType.VARIANT, variant_gid)
        if variant_entity is None:
            variant_entity = entities.get_by_shopify_gid(session, EntityType.PRODUCT, variant_gid)
        if variant_entity is None or variant_entity.erpnext_name is None:
            continue
        qty = int(line.get("quantity") or 0)
        fulfilled_lines.append({"variant_gid": variant_gid, "quantity": qty})
        dn_items.append(
            {"item_code": variant_entity.erpnext_name, "qty": qty, "against_sales_order": sales_order}
        )

    canonical = canonicalize(EntityType.FULFILLMENT, {"line_items": fulfilled_lines})
    fp = fingerprint(canonical)

    entity = _fulfillment_entity(session, order_gid)
    if entity is not None and entity.shopify_fingerprint == fp:
        return  # Echo: our own write from issue 19.

    fulfillment_gid = _fulfillment_gid(payload)
    delivery_note = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "customer": _order_customer(erpnext_client, sales_order),
            "against_sales_order": sales_order,
            "shopify_fulfillment_gid": fulfillment_gid,
            "items": dn_items,
        }
    )
    erpnext_client.submit(delivery_note)

    entities.save(
        session,
        entity,
        entity_type=EntityType.FULFILLMENT,
        shopify_gid=fulfillment_gid,
        group_key=order_gid,
        erpnext_doctype="Delivery Note",
        erpnext_name=delivery_note["name"],
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )


def _order_customer(erpnext_client: ERPNextClientProtocol, sales_order: str) -> str | None:
    try:
        return erpnext_client.get_doc("Sales Order", sales_order).get("customer")
    except LookupError:
        return None


def _fulfillment_order_gid(payload: dict[str, Any]) -> str:
    order = payload.get("order") or {}
    gid = order.get("admin_graphql_api_id") or payload.get("order_gid")
    if gid:
        return gid
    order_id = payload.get("order_id")
    if order_id is not None:
        return f"gid://shopify/Order/{order_id}"
    raise ValueError("Shopify fulfillment is missing its order reference")


def _fulfillment_gid(payload: dict[str, Any]) -> str:
    gid = payload.get("admin_graphql_api_id") or payload.get("id")
    if isinstance(gid, str) and gid.startswith("gid://"):
        return gid
    return f"gid://shopify/Fulfillment/{gid}"
