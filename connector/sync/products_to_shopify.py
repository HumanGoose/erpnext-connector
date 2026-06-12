"""ERPNext Item -> Shopify product/variant sync (issues 07, 09).

Driven by the Frappe Webhook on Item create/update. Only Items whose template
has "Sync to Shopify" enabled are pushed (variant Items inherit their
template's flag); everything else short-circuits before any `ShopifyClient`
call. Echo detection runs against the stored `erpnext_fingerprint` so the
Connector never re-pushes its own prior write.
"""

from typing import Any

from sqlmodel import Session

from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType
from connector.shopify.client import ShopifyClientProtocol
from connector.sync import entities

DEFAULT_PRICE_LIST = "Standard Selling"


def handle_item_webhook(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Sync an ERPNext Item create/update to Shopify, if sync-enabled."""
    if not _sync_enabled(erpnext_client, payload):
        return  # Not opted in (per issue 07) — no ShopifyClient calls.

    if payload.get("has_variants"):
        _sync_template(session, shopify_client, erpnext_client, payload)
    elif payload.get("variant_of"):
        _sync_variant(session, shopify_client, erpnext_client, payload)
    else:
        _sync_simple_item(session, shopify_client, erpnext_client, payload)


def handle_item_price_webhook(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Sync an ERPNext Item Price change to the Shopify variant's price (issue 11).

    Fires on the Frappe Webhook for Item Price on the configured Price List.
    Resolves the priced Item to its variant (or simple-product) Synced Entity,
    Echo-checks against `erpnext_fingerprint`, and pushes the new price."""
    if payload.get("price_list") != DEFAULT_PRICE_LIST:
        return
    item_code = payload.get("item_code")
    if not item_code:
        return

    item = erpnext_client.get_doc("Item", item_code)
    if not _sync_enabled(erpnext_client, item):
        return

    entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", item_code)
    if entity is not None:
        canonical = _variant_canonical(erpnext_client, item)
        product_gid = entity.group_key
    else:
        entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item_code)
        if entity is None:
            return  # Item not synced to Shopify yet.
        canonical = _template_canonical(erpnext_client, item)
        product_gid = entity.shopify_gid

    fp = fingerprint(canonical)
    if entity.erpnext_fingerprint == fp:
        return  # Echo: this price is our own prior write (issue 10).

    variant_gid = item.get("shopify_variant_gid") or (
        entity.shopify_gid if entity.entity_type == EntityType.VARIANT else None
    )
    price = f"{float(payload['price_list_rate']):.2f}"
    if variant_gid and product_gid:
        shopify_client.update_variant_price(product_gid, variant_gid, price)

    entity.erpnext_fingerprint = fp
    entity.shopify_fingerprint = fp
    entities.save(session, entity)


def _sync_enabled(erpnext_client: ERPNextClientProtocol, item: dict[str, Any]) -> bool:
    """Whether this Item is opted into Shopify sync. Variant Items inherit the
    flag from their template (the flag lives on the template only)."""
    template_name = item.get("variant_of")
    if template_name:
        template = erpnext_client.get_doc("Item", template_name)
        return bool(template.get("sync_to_shopify"))
    return bool(item.get("sync_to_shopify"))


def item_to_product_raw(erpnext_client: ERPNextClientProtocol, item: dict[str, Any]) -> dict[str, Any]:
    """Build the ERPNext-side raw shape `canonicalize("product", ...)` expects,
    from a template Item. Shared with the reconciliation pass (issue 14).

    Option values are reconstructed from the template's variant Items so the
    canonical matches the Shopify-side form (which carries option values)."""
    variants = erpnext_client.get_list(
        "Item", filters={"variant_of": item["name"]}, fields=["*"]
    )
    options = []
    for attribute in item.get("attributes") or []:
        name = attribute.get("attribute")
        values: list[str] = []
        for variant in variants:
            for attr in variant.get("attributes") or []:
                if attr.get("attribute") == name and attr.get("attribute_value") not in values:
                    values.append(attr["attribute_value"])
        options.append({"name": name, "values": values})

    return {
        "title": item.get("item_name") or item.get("item_code"),
        "descriptionHtml": item.get("description") or "",
        "options": options,
        "featured_image": item.get("image") or "",
        "media": _item_media(erpnext_client, item["name"]),
    }


def _template_canonical(erpnext_client: ERPNextClientProtocol, item: dict[str, Any]) -> dict[str, Any]:
    return canonicalize(EntityType.PRODUCT, item_to_product_raw(erpnext_client, item))


def _item_media(erpnext_client: ERPNextClientProtocol, item_name: str) -> list[str]:
    """The Item's image File attachments, ordered, as URLs (for issue 09)."""
    files = erpnext_client.get_list(
        "File",
        filters={"attached_to_doctype": "Item", "attached_to_name": item_name},
        fields=["file_url"],
    )
    return [row["file_url"] for row in files if row.get("file_url")]


def _variant_price(erpnext_client: ERPNextClientProtocol, item_code: str) -> str:
    matches = erpnext_client.get_list(
        "Item Price",
        filters={"item_code": item_code, "price_list": DEFAULT_PRICE_LIST},
        fields=["price_list_rate"],
    )
    if matches:
        return f"{float(matches[0]['price_list_rate']):.2f}"
    return ""


def item_to_variant_raw(erpnext_client: ERPNextClientProtocol, item: dict[str, Any]) -> dict[str, Any]:
    """Build the ERPNext-side raw shape `canonicalize("variant", ...)` expects,
    from a variant Item. Shared with the reconciliation pass (issue 14)."""
    return {
        "sku": item.get("item_code"),
        "title": item.get("item_name") or item.get("item_code"),
        "selected_options": [
            {"name": attr.get("attribute"), "value": attr.get("attribute_value")}
            for attr in item.get("attributes") or []
        ],
        "price": _variant_price(erpnext_client, item["item_code"]),
    }


def _variant_canonical(erpnext_client: ERPNextClientProtocol, item: dict[str, Any]) -> dict[str, Any]:
    return canonicalize(EntityType.VARIANT, item_to_variant_raw(erpnext_client, item))


def _sync_template(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    item: dict[str, Any],
) -> None:
    canonical = _template_canonical(erpnext_client, item)
    fp = fingerprint(canonical)

    entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["name"])
    if entity is not None and entity.erpnext_fingerprint == fp:
        return  # Echo: our own prior write.

    product_input = {
        "title": canonical["title"],
        "descriptionHtml": canonical["description"],
        "productOptions": [
            {"name": option["name"], "values": [{"name": value} for value in option["values"]]}
            for option in canonical["options"]
        ],
    }

    if entity is None or not item.get("shopify_product_gid"):
        product = shopify_client.create_product(product_input)
        product_gid = product["id"]
        erpnext_client.set_value("Item", item["name"], "shopify_product_gid", product_gid)
    else:
        product_gid = item["shopify_product_gid"]
        shopify_client.update_product(product_gid, product_input)

    if canonical["media"]:
        shopify_client.append_product_media(product_gid, canonical["media"])

    entities.save(
        session,
        entity,
        entity_type=EntityType.PRODUCT,
        shopify_gid=product_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=item["name"],
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )


def _sync_variant(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    item: dict[str, Any],
) -> None:
    canonical = _variant_canonical(erpnext_client, item)
    fp = fingerprint(canonical)

    entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", item["name"])
    if entity is not None and entity.erpnext_fingerprint == fp:
        return  # Echo.

    template_entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["variant_of"])
    if template_entity is None or template_entity.shopify_gid is None:
        return  # Template not yet synced to Shopify; nothing to attach to.
    product_gid = template_entity.shopify_gid

    variant_input = {
        "sku": canonical["sku"],
        "optionValues": [
            {"name": option["value"], "optionName": option["name"]}
            for option in canonical["selected_options"]
        ],
    }
    if canonical["price"]:
        variant_input["price"] = canonical["price"]

    if entity is None or not item.get("shopify_variant_gid"):
        created = shopify_client.create_variants(product_gid, [variant_input])
        variant_gid = created[0]["id"]
        erpnext_client.set_value("Item", item["name"], "shopify_variant_gid", variant_gid)
    else:
        variant_gid = item["shopify_variant_gid"]
        if canonical["price"]:
            shopify_client.update_variant_price(product_gid, variant_gid, canonical["price"])

    entities.save(
        session,
        entity,
        entity_type=EntityType.VARIANT,
        shopify_gid=variant_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=item["name"],
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )


def _sync_simple_item(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    item: dict[str, Any],
) -> None:
    """A non-variant ERPNext Item maps to a Shopify product with one default variant."""
    canonical = _template_canonical(erpnext_client, item)
    fp = fingerprint(canonical)

    entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["name"])
    if entity is not None and entity.erpnext_fingerprint == fp:
        return  # Echo.

    price = _variant_price(erpnext_client, item["item_code"])
    product_input: dict[str, Any] = {
        "title": canonical["title"],
        "descriptionHtml": canonical["description"],
    }

    if entity is None or not item.get("shopify_product_gid"):
        default_variant: dict[str, Any] = {"sku": item.get("item_code") or ""}
        if price:
            default_variant["price"] = price
        product_input["variants"] = [default_variant]
        product = shopify_client.create_product(product_input)
        product_gid = product["id"]
        variant_gid = (product.get("variants") or [{}])[0].get("id")
        erpnext_client.set_value("Item", item["name"], "shopify_product_gid", product_gid)
        if variant_gid:
            erpnext_client.set_value("Item", item["name"], "shopify_variant_gid", variant_gid)
    else:
        product_gid = item["shopify_product_gid"]
        shopify_client.update_product(product_gid, product_input)

    if canonical["media"]:
        shopify_client.append_product_media(product_gid, canonical["media"])

    entities.save(
        session,
        entity,
        entity_type=EntityType.PRODUCT,
        shopify_gid=product_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=item["name"],
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )
