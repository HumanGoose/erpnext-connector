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
from connector.sync.inventory import push_item_inventory, seed_inventory_entity

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
    """Whether this Item is opted into Shopify sync.

    Already-linked items (with a Shopify GID) always sync back — the flag only
    gates *creation* of new products in Shopify. Variant Items inherit the flag
    from their template."""
    if item.get("shopify_product_gid") or item.get("shopify_variant_gid"):
        return True
    template_name = item.get("variant_of")
    if template_name:
        template = erpnext_client.get_doc("Item", template_name)
        return bool(template.get("sync_to_shopify")) or bool(
            template.get("shopify_product_gid")
        )
    return bool(item.get("sync_to_shopify"))


_VALID_SHOPIFY_STATUSES = {"ACTIVE", "DRAFT", "ARCHIVED", "UNLISTED"}


def _parse_collections(raw: str) -> list[str]:
    """Parse a comma-separated list of Shopify Collection GIDs from an ERPNext field."""
    return [c.strip() for c in raw.split(",") if c.strip()]


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
        "vendor": item.get("shopify_vendor") or "",
        "product_type": item.get("item_group") or "",
        "tags": item.get("shopify_tags") or "",
        "featured_image": item.get("image") or "",
        "media": _item_media(erpnext_client, item["name"]),
        # disabled=1 in ERPNext is the semantic equivalent of Shopify ARCHIVED —
        # the item can no longer be sold. Override shopify_status so this
        # propagates even when ERPNext rejects a hard-delete due to linked
        # transactions and the user disables the item as a fallback.
        "status": "Archived" if item.get("disabled") else (item.get("shopify_status") or "Active"),
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
        "image": item.get("image") or "",
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
    shopify_fp = fingerprint(canonical)
    # erpnext_fp extends the canonical with ERPNext-only fields (collections,
    # category) so that changing only those fields still triggers a sync.
    collections = _parse_collections(item.get("shopify_collections") or "")
    category_gid = item.get("shopify_category_gid") or ""
    erpnext_fp = fingerprint({**canonical, "collections": sorted(collections), "category": category_gid})

    entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["name"])
    if entity is not None and entity.erpnext_fingerprint == erpnext_fp:
        return  # Echo: our own prior write.

    shopify_status = canonical.get("status") or "ACTIVE"
    if shopify_status not in _VALID_SHOPIFY_STATUSES:
        shopify_status = "ACTIVE"
    base_input: dict[str, Any] = {
        "title": canonical["title"],
        "descriptionHtml": canonical["description"],
        "status": shopify_status,
    }
    if canonical.get("vendor"):
        base_input["vendor"] = canonical["vendor"]
    if canonical.get("product_type"):
        base_input["productType"] = canonical["product_type"]
    if canonical.get("tags"):
        base_input["tags"] = canonical["tags"]
    if collections:
        base_input["collectionsToJoin"] = collections
    if category_gid:
        base_input["category"] = {"id": category_gid}

    if not item.get("shopify_product_gid"):
        # Defer creation until at least one variant exists — Shopify rejects
        # productCreate with productOptions that have empty values arrays.
        if canonical["options"] and not any(option["values"] for option in canonical["options"]):
            return
        product_input = {
            **base_input,
            "productOptions": [
                {"name": option["name"], "values": [{"name": value} for value in option["values"]]}
                for option in canonical["options"]
            ],
        }
        product = shopify_client.create_product(product_input)
        product_gid = product["id"]
        erpnext_client.set_value("Item", item["name"], "shopify_product_gid", product_gid)
    else:
        product_gid = item["shopify_product_gid"]
        shopify_client.update_product(product_gid, base_input)

    if canonical.get("media"):
        shopify_client.append_product_media(product_gid, canonical["media"])

    entities.save(
        session,
        entity,
        entity_type=EntityType.PRODUCT,
        shopify_gid=product_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=item["name"],
        shopify_fingerprint=shopify_fp,
        erpnext_fingerprint=erpnext_fp,
    )


def handle_item_delete_webhook(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Sync an ERPNext Item deletion to Shopify.

    Called by the Frappe Server Script hook on Item after_delete. The payload
    carries the GIDs that were on the item before deletion.
    """
    product_gid = payload.get("shopify_product_gid") or ""
    variant_gid = payload.get("shopify_variant_gid") or ""
    variant_of = payload.get("variant_of") or ""
    item_name = payload.get("name") or ""

    if not product_gid:
        # GID missing from payload — set_value may have failed due to a MySQL
        # deadlock before the item was deleted. Fall back to SyncedEntity which
        # always has the correct GIDs regardless of ERPNext field state.
        product_entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item_name)
        variant_entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", item_name)
        if product_entity:
            product_gid = product_entity.shopify_gid or ""
        elif variant_entity:
            product_gid = variant_entity.group_key or ""
            variant_gid = variant_entity.shopify_gid or ""
            variant_of = "_"  # non-empty: signals variant-only delete below
        if not product_gid:
            return  # Genuinely never synced to Shopify.

    # Only call delete_variants for genuine ERPNext variant items (variant_of is set).
    # Simple items (single-variant Shopify products) carry both GIDs but have no
    # variant_of, and are stored as PRODUCT entities — delete the whole product.
    if variant_gid and variant_of:
        try:
            shopify_client.delete_variants(product_gid, [variant_gid])
        except Exception:
            pass
        entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", item_name)
        if entity is not None:
            session.delete(entity)
            session.commit()
    else:
        try:
            shopify_client.delete_product(product_gid)
        except Exception:
            pass
        # Delete ALL entities scoped to this product: PRODUCT, VARIANT, INVENTORY_LEVEL.
        for related_entity in entities.get_group(session, product_gid):
            session.delete(related_entity)
        session.commit()


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
        # Template not yet in Shopify (deferred because no variants existed when
        # the template item was saved). Try to create it now — this variant's
        # option values are already in ERPNext so the product options will be valid.
        try:
            template_item = erpnext_client.get_doc("Item", item["variant_of"])
        except Exception:
            return
        _sync_template(session, shopify_client, erpnext_client, template_item)
        template_entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["variant_of"])
        if template_entity is None or template_entity.shopify_gid is None:
            return  # Still no valid options — bail.
    product_gid = template_entity.shopify_gid

    variant_input: dict[str, Any] = {
        "inventoryItem": {"sku": canonical["sku"]},
        "optionValues": [
            {"name": option["value"], "optionName": option["name"]}
            for option in canonical["selected_options"]
        ],
    }
    if canonical["price"]:
        variant_input["price"] = canonical["price"]
    if canonical.get("image"):
        image_id = shopify_client.get_or_create_product_image_id(product_gid, canonical["image"])
        if image_id:
            variant_input["imageId"] = image_id

    if not item.get("shopify_variant_gid"):
        created = shopify_client.create_variants(product_gid, [variant_input])
        first = created[0]
        variant_gid = first["id"]
        inventory_item_gid = (first.get("inventoryItem") or {}).get("id") or ""
        erpnext_client.set_value("Item", item["name"], "shopify_variant_gid", variant_gid)
        if inventory_item_gid:
            erpnext_client.set_value("Item", item["name"], "shopify_inventory_item_gid", inventory_item_gid)
            seed_inventory_entity(session, inventory_item_gid, product_gid, item["name"])
            push_item_inventory(session, shopify_client, erpnext_client, item["name"])
    else:
        variant_gid = item["shopify_variant_gid"]
        shopify_client.update_variants(product_gid, [{**variant_input, "id": variant_gid}])

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
    collections = _parse_collections(item.get("shopify_collections") or "")
    category_gid = item.get("shopify_category_gid") or ""
    erpnext_fp = fingerprint({**canonical, "collections": sorted(collections), "category": category_gid})

    entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["name"])
    if entity is not None and entity.erpnext_fingerprint == erpnext_fp:
        return  # Echo.

    price = _variant_price(erpnext_client, item["item_code"])
    # shopify_fp must include sku+price to match the fingerprint _sync_simple_product
    # computes from the Shopify products/create webhook, so the echo check on that
    # side correctly suppresses the callback and prevents an update loop.
    shopify_fp = fingerprint({**canonical, "sku": item.get("item_code") or "", "price": price or ""})
    shopify_status = canonical.get("status") or "ACTIVE"
    if shopify_status not in _VALID_SHOPIFY_STATUSES:
        shopify_status = "ACTIVE"
    product_input: dict[str, Any] = {
        "title": canonical["title"],
        "descriptionHtml": canonical["description"],
        "status": shopify_status,
    }
    if canonical.get("vendor"):
        product_input["vendor"] = canonical["vendor"]
    if canonical.get("product_type"):
        product_input["productType"] = canonical["product_type"]
    if canonical.get("tags"):
        product_input["tags"] = canonical["tags"]
    if collections:
        product_input["collectionsToJoin"] = collections
    if category_gid:
        product_input["category"] = {"id": category_gid}

    # Guard on the GID field only, not entity presence: set_value writes the GID
    # back to ERPNext before entities.save completes, so a concurrent webhook
    # from that writeback would see entity=None but shopify_product_gid already
    # set — using entity is None here would create a duplicate Shopify product.
    if not item.get("shopify_product_gid"):
        default_variant: dict[str, Any] = {"inventoryItem": {"sku": item.get("item_code") or "", "tracked": True}}
        if price:
            default_variant["price"] = price
        product_input["variants"] = [default_variant]
        product = shopify_client.create_product(product_input)
        product_gid = product["id"]
        first_variant = (product.get("variants") or [{}])[0]
        variant_gid = first_variant.get("id")
        inventory_item_gid = (first_variant.get("inventoryItem") or {}).get("id") or ""
        erpnext_client.set_value("Item", item["name"], "shopify_product_gid", product_gid)
        if variant_gid:
            erpnext_client.set_value("Item", item["name"], "shopify_variant_gid", variant_gid)
        if inventory_item_gid:
            erpnext_client.set_value("Item", item["name"], "shopify_inventory_item_gid", inventory_item_gid)
            seed_inventory_entity(session, inventory_item_gid, product_gid, item["name"])
            push_item_inventory(session, shopify_client, erpnext_client, item["name"])
    else:
        product_gid = item["shopify_product_gid"]
        shopify_client.update_product(product_gid, product_input)

    if canonical.get("media"):
        shopify_client.append_product_media(product_gid, canonical["media"])

    entities.save(
        session,
        entity,
        entity_type=EntityType.PRODUCT,
        shopify_gid=product_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=item["name"],
        shopify_fingerprint=shopify_fp,
        erpnext_fingerprint=erpnext_fp,
    )
