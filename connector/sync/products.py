"""Shopify product/variant -> ERPNext Item sync (issue 05).

Handles the `products/create` and `products/update` webhook topics: Echo
detection (per ADR-0003) against the stored `shopify_fingerprint`, then
create/update of the corresponding ERPNext template + variant Items (or a
single non-variant Item for single-variant products), per the PRD's
Product & Variant mapping.
"""

import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncedEntity
from connector.sync import entities as sync_entities
from connector.sync.inventory import seed_inventory_entity

logger = logging.getLogger(__name__)


class ItemDeletedError(Exception):
    """Raised when _upsert_item cannot update because the item was concurrently deleted."""

# Defaults required by ERPNext's Item doctype that the PRD doesn't otherwise
# specify; both exist in a fresh ERPNext install.
DEFAULT_ITEM_GROUP = "All Item Groups"
DEFAULT_STOCK_UOM = "Nos"
# A Shopify variant's price maps to an Item Price on this single Price List (per PRD).
DEFAULT_PRICE_LIST = "Standard Selling"


def _sync_variant_price(erpnext_client: ERPNextClientProtocol, item_code: str, price: Any) -> None:
    """Upsert the ERPNext Item Price for a variant on the configured Price List (issue 10).

    A no-op when the price is absent or already matches, so an Echo (or a
    non-price change) makes no redundant write.
    """
    if price in (None, ""):
        return
    rate = float(price)

    matches = erpnext_client.get_list(
        "Item Price",
        filters={"item_code": item_code, "price_list": DEFAULT_PRICE_LIST},
        fields=["name", "price_list_rate"],
    )
    if matches:
        if float(matches[0]["price_list_rate"]) == rate:
            return
        erpnext_client.update(
            {"doctype": "Item Price", "name": matches[0]["name"], "price_list_rate": rate}
        )
    else:
        erpnext_client.insert(
            {
                "doctype": "Item Price",
                "item_code": item_code,
                "price_list": DEFAULT_PRICE_LIST,
                "price_list_rate": rate,
            }
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _money_str(value: Any) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value):.2f}"


def handle_product_webhook(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Sync a Shopify `products/create`/`products/update` payload to ERPNext."""
    product_gid = _gid(payload)
    canonical_product = canonicalize(EntityType.PRODUCT, payload)
    product_fingerprint = fingerprint(canonical_product)
    raw_variants = _raw_variants(payload)

    try:
        if _is_simple_product(canonical_product, raw_variants):
            _sync_simple_product(
                session, erpnext_client, payload, product_gid, canonical_product, product_fingerprint, raw_variants[0]
            )
            return

        _sync_template_product(
            session, erpnext_client, payload, product_gid, canonical_product, product_fingerprint, raw_variants
        )
    except ItemDeletedError as exc:
        logger.info("Shopify product %s skipped: ERPNext item %r was deleted", product_gid, str(exc))


def is_archived(payload: dict[str, Any]) -> bool:
    """Whether a `products/update` payload represents a product moved to "archived".

    Shopify has no separate webhook topic for archiving — it's a `status`
    change delivered via `products/update`. REST/webhook payloads use
    lowercase status strings (`"archived"`); GraphQL uses the uppercase enum
    (`"ARCHIVED"`).
    """
    return str(payload.get("status", "")).upper() == "ARCHIVED"


def handle_product_disable(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Delete (or disable) ERPNext Items when a Shopify product is hard-deleted.

    Tries to delete each Item outright; falls back to disabling it if ERPNext
    rejects the deletion (e.g. item has linked transactions).
    """
    product_gid = _gid(payload)

    template_entity = _get_synced_entity(session, EntityType.PRODUCT, product_gid)
    if template_entity is None:
        return

    for variant_entity in _get_variant_entities(session, product_gid):
        _delete_or_disable_item(erpnext_client, variant_entity)
    _delete_or_disable_item(erpnext_client, template_entity)


def _delete_or_disable_item(erpnext_client: ERPNextClientProtocol, entity: SyncedEntity) -> None:
    if entity.erpnext_name is None:
        return
    try:
        erpnext_client.delete("Item", entity.erpnext_name)
    except Exception:
        try:
            erpnext_client.set_value("Item", entity.erpnext_name, "disabled", 1)
        except Exception:
            pass


def _get_variant_entities(session: Session, product_gid: str) -> list[SyncedEntity]:
    statement = select(SyncedEntity).where(
        SyncedEntity.entity_type == EntityType.VARIANT,
        SyncedEntity.group_key == product_gid,
    )
    return list(session.exec(statement).all())


def _sync_template_product(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
    product_gid: str,
    canonical_product: dict[str, Any],
    product_fingerprint: str,
    raw_variants: list[dict[str, Any]],
) -> None:
    template_entity = _get_synced_entity(session, EntityType.PRODUCT, product_gid)
    existing_name = template_entity.erpnext_name if template_entity else None
    template_item_code = existing_name or payload.get("handle") or product_gid

    if template_entity is None or template_entity.shopify_fingerprint != product_fingerprint:
        _ensure_item_attributes(erpnext_client, canonical_product["options"])
        item_group = _ensure_item_group(erpnext_client, canonical_product.get("product_type") or "")
        template_doc = _build_template_doc(template_item_code, canonical_product, product_gid, item_group)
        result = _upsert_item(erpnext_client, template_doc, existing_name)

        # Store the ERPNext-side fingerprint (with empty collections/category)
        # so the on_update echo check in products_to_shopify matches immediately.
        erpnext_fp = fingerprint({**canonical_product, "collections": [], "category": ""})
        template_entity = _save_synced_entity(
            session,
            template_entity,
            entity_type=EntityType.PRODUCT,
            shopify_gid=product_gid,
            group_key=product_gid,
            erpnext_doctype="Item",
            erpnext_name=result["name"],
            shopify_fingerprint=product_fingerprint,
            erpnext_fingerprint=erpnext_fp,
        )
        _sync_product_images(erpnext_client, result["name"], canonical_product)

    incoming_variant_gids = {_gid(v, "ProductVariant") for v in raw_variants}
    for variant_entity in _get_variant_entities(session, product_gid):
        if variant_entity.shopify_gid not in incoming_variant_gids:
            _delete_or_disable_item(erpnext_client, variant_entity)

    product_status = canonical_product.get("status", "ACTIVE")
    for raw_variant in raw_variants:
        variant_image = _variant_image_url(raw_variant, payload)
        _sync_variant(session, erpnext_client, raw_variant, canonical_product["options"], product_gid, template_entity.erpnext_name, product_status, variant_image)


def _sync_variant(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    raw_variant: dict[str, Any],
    product_options: list[dict[str, Any]],
    product_gid: str,
    template_item_code: str,
    product_status: str = "ACTIVE",
    image_url: str = "",
) -> None:
    variant_gid = _gid(raw_variant, resource="ProductVariant")
    selected_options = _variant_selected_options(raw_variant, product_options)
    canonical_variant = canonicalize(EntityType.VARIANT, {**raw_variant, "selected_options": selected_options, "image": image_url})
    variant_fingerprint = fingerprint(canonical_variant)

    variant_entity = _get_synced_entity(session, EntityType.VARIANT, variant_gid)
    if variant_entity is not None and variant_entity.shopify_fingerprint == variant_fingerprint:
        # Variant data unchanged, but status may have changed at the product level.
        if variant_entity.erpnext_name:
            _apply_product_status_to_variant(erpnext_client, variant_entity.erpnext_name, product_status)
        return

    inventory_item_gid = _inventory_item_gid(raw_variant)
    existing_name = variant_entity.erpnext_name if variant_entity else None
    desired_item_code = canonical_variant["sku"] or variant_gid
    # item_code is immutable in ERPNext once set — reuse the existing name on updates.
    item_code = existing_name or desired_item_code
    variant_doc = _build_variant_doc(item_code, template_item_code, canonical_variant, product_gid, variant_gid, inventory_item_gid, product_status, image_url)
    result = _upsert_item(erpnext_client, variant_doc, existing_name, desired_item_code)

    # Shopify variant price -> ERPNext Item Price (issue 10).
    _sync_variant_price(erpnext_client, result["name"], canonical_variant["price"])

    _save_synced_entity(
        session,
        variant_entity,
        entity_type=EntityType.VARIANT,
        shopify_gid=variant_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=result["name"],
        shopify_fingerprint=variant_fingerprint,
        erpnext_fingerprint=variant_fingerprint,
    )

    if inventory_item_gid:
        seed_inventory_entity(session, inventory_item_gid, variant_gid, result["name"])


def _sync_simple_product(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
    product_gid: str,
    canonical_product: dict[str, Any],
    product_fingerprint: str,
    raw_variant: dict[str, Any],
) -> None:
    variant_gid = _gid(raw_variant, resource="ProductVariant")
    sku = raw_variant.get("sku") or ""
    # Include price so a price-only change on a simple product is a genuine
    # change (drives Item Price sync, issue 10) rather than an Echo.
    canonical = {**canonical_product, "sku": sku, "price": _money_str(raw_variant.get("price"))}
    item_fingerprint = fingerprint(canonical)

    entity = _get_synced_entity(session, EntityType.PRODUCT, product_gid)
    if entity is not None and entity.shopify_fingerprint == item_fingerprint:
        return  # Echo: nothing tracked has changed.

    inventory_item_gid = _inventory_item_gid(raw_variant)
    existing_name = entity.erpnext_name if entity else None
    desired_item_code = sku or payload.get("handle") or product_gid
    # item_code is immutable in ERPNext once set — reuse the existing name on updates.
    item_code = existing_name or desired_item_code
    item_group = _ensure_item_group(erpnext_client, canonical_product.get("product_type") or "")
    status = canonical_product.get("status", "ACTIVE")
    doc = {
        "name": item_code,
        "item_code": item_code,
        "item_name": canonical_product["title"],
        "description": canonical_product["description"],
        "item_group": item_group,
        "stock_uom": DEFAULT_STOCK_UOM,
        "has_variants": 0,
        "shopify_product_gid": product_gid,
        "shopify_variant_gid": variant_gid,
        "shopify_inventory_item_gid": inventory_item_gid,
        "shopify_vendor": canonical_product.get("vendor") or "",
        "shopify_tags": ", ".join(canonical_product.get("tags") or []),
        "shopify_status": status.title(),
        "disabled": 1 if status == "ARCHIVED" else 0,
        "image": canonical_product.get("featured_image", ""),
    }
    result = _upsert_item(erpnext_client, doc, existing_name, desired_item_code)

    _sync_variant_price(erpnext_client, result["name"], raw_variant.get("price"))

    # erpnext_fp must use canonical_product (no sku/price) to match the formula
    # _sync_simple_item uses: that handler computes erpnext_fp from _template_canonical
    # which excludes sku/price, so both sides converge on the same hash and the
    # ERPNext on_update echo-check fires correctly after this write.
    erpnext_fp = fingerprint({**canonical_product, "collections": [], "category": ""})
    _save_synced_entity(
        session,
        entity,
        entity_type=EntityType.PRODUCT,
        shopify_gid=product_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=result["name"],
        shopify_fingerprint=item_fingerprint,
        erpnext_fingerprint=erpnext_fp,
    )
    _sync_product_images(erpnext_client, result["name"], canonical_product)

    if inventory_item_gid:
        seed_inventory_entity(session, inventory_item_gid, product_gid, result["name"])


def _build_template_doc(
    item_code: str,
    canonical_product: dict[str, Any],
    product_gid: str,
    item_group: str,
) -> dict[str, Any]:
    status = canonical_product.get("status", "ACTIVE")
    return {
        "name": item_code,
        "item_code": item_code,
        "item_name": canonical_product["title"],
        "description": canonical_product["description"],
        "item_group": item_group,
        "stock_uom": DEFAULT_STOCK_UOM,
        "has_variants": 1,
        "attributes": [{"attribute": option["name"]} for option in canonical_product["options"]],
        "shopify_product_gid": product_gid,
        "shopify_vendor": canonical_product.get("vendor") or "",
        "shopify_tags": ", ".join(canonical_product.get("tags") or []),
        "shopify_status": status.title(),
        "disabled": 1 if status == "ARCHIVED" else 0,
        "image": canonical_product.get("featured_image", ""),
    }


def _sync_product_images(
    erpnext_client: ERPNextClientProtocol,
    item_name: str,
    canonical_product: dict[str, Any],
) -> None:
    """Attach the Shopify product's images as Files linked to the ERPNext Item.

    Per the PRD Image mapping: the featured image is the Item's `image` field
    (set on the Item doc by the caller) and *all* images are File attachments.
    Already-attached URLs are skipped so repeated syncs don't duplicate Files.
    """
    media = canonical_product.get("media") or []
    if not media:
        return

    existing = erpnext_client.get_list(
        "File",
        filters={"attached_to_doctype": "Item", "attached_to_name": item_name},
        fields=["file_url"],
    )
    attached_urls = {row.get("file_url") for row in existing}

    for url in media:
        if url in attached_urls:
            continue
        erpnext_client.insert(
            {
                "doctype": "File",
                "file_url": url,
                "attached_to_doctype": "Item",
                "attached_to_name": item_name,
            }
        )


def _build_variant_doc(
    item_code: str,
    template_item_code: str,
    canonical_variant: dict[str, Any],
    product_gid: str,
    variant_gid: str,
    inventory_item_gid: str,
    product_status: str = "ACTIVE",
    image_url: str = "",
) -> dict[str, Any]:
    return {
        "name": item_code,
        "item_code": item_code,
        "item_name": canonical_variant["title"],
        "item_group": DEFAULT_ITEM_GROUP,
        "stock_uom": DEFAULT_STOCK_UOM,
        "has_variants": 0,
        "variant_of": template_item_code,
        "attributes": [
            {"attribute": option["name"], "attribute_value": option["value"]}
            for option in canonical_variant["selected_options"]
        ],
        "shopify_product_gid": product_gid,
        "shopify_variant_gid": variant_gid,
        "shopify_inventory_item_gid": inventory_item_gid,
        "shopify_status": product_status.title(),
        "disabled": 1 if product_status == "ARCHIVED" else 0,
        "image": image_url,
    }


def _apply_product_status_to_variant(
    erpnext_client: ERPNextClientProtocol,
    item_name: str,
    product_status: str,
) -> None:
    """Push the product-level status down to a variant Item that hasn't otherwise changed."""
    desired_status = product_status.title()
    desired_disabled = 1 if product_status == "ARCHIVED" else 0
    try:
        item = erpnext_client.get_doc("Item", item_name)
    except Exception:
        return
    if item is None:
        return
    if item.get("shopify_status") != desired_status:
        erpnext_client.set_value("Item", item_name, "shopify_status", desired_status)
    if bool(item.get("disabled")) != bool(desired_disabled):
        erpnext_client.set_value("Item", item_name, "disabled", desired_disabled)


def _variant_image_url(raw_variant: dict[str, Any], payload: dict[str, Any]) -> str:
    """Extract the image URL for a variant from the product webhook payload.

    REST webhooks carry `image_id` (numeric) on the variant and the full image
    objects (with `src`) in `payload["images"]`. GraphQL payloads may carry
    `image.url` directly on the variant node.
    """
    image = raw_variant.get("image")
    if isinstance(image, dict):
        return image.get("url") or image.get("src") or ""

    image_id = raw_variant.get("image_id")
    if image_id:
        for img in payload.get("images") or []:
            if img.get("id") == image_id:
                return img.get("src") or ""
    return ""


def _inventory_item_gid(raw_variant: dict[str, Any]) -> str:
    """Extract the Shopify InventoryItem GID from a variant payload.

    GraphQL variant nodes carry `inventoryItem.id`; webhook/REST payloads carry
    the numeric `inventory_item_id`.
    """
    gid = (raw_variant.get("inventoryItem") or {}).get("id")
    if gid:
        return str(gid)
    raw_id = raw_variant.get("inventory_item_id")
    if raw_id is None:
        return ""
    if isinstance(raw_id, str) and raw_id.startswith("gid://"):
        return raw_id
    return f"gid://shopify/InventoryItem/{raw_id}"


def _ensure_item_group(erpnext_client: ERPNextClientProtocol, product_type: str) -> str:
    """Return the ERPNext Item Group name for `product_type`, creating it if absent."""
    if not product_type:
        return DEFAULT_ITEM_GROUP
    existing = erpnext_client.get_list("Item Group", filters={"name": product_type}, fields=["name"])
    if existing:
        return product_type
    erpnext_client.insert({
        "doctype": "Item Group",
        "item_group_name": product_type,
        "parent_item_group": DEFAULT_ITEM_GROUP,
    })
    return product_type


def _ensure_item_attributes(erpnext_client: ERPNextClientProtocol, options: list[dict[str, Any]]) -> None:
    """Create or update "Item Attribute" docs so all variant values are valid."""
    for option in options:
        existing = erpnext_client.get_list("Item Attribute", filters={"name": option["name"]}, fields=["name"])
        if not existing:
            erpnext_client.insert(
                {
                    "doctype": "Item Attribute",
                    "name": option["name"],
                    "attribute_name": option["name"],
                    "item_attribute_values": [
                        {"attribute_value": value, "abbr": value} for value in option["values"]
                    ],
                }
            )
            continue

        attr_doc = erpnext_client.get_doc("Item Attribute", option["name"])
        existing_values = {row["attribute_value"] for row in attr_doc.get("item_attribute_values") or []}
        new_values = [v for v in option["values"] if v not in existing_values]
        if not new_values:
            continue

        merged = list(attr_doc.get("item_attribute_values") or []) + [
            {"attribute_value": value, "abbr": value} for value in new_values
        ]
        erpnext_client.update(
            {
                "doctype": "Item Attribute",
                "name": option["name"],
                "item_attribute_values": merged,
            }
        )


def _upsert_item(
    erpnext_client: ERPNextClientProtocol,
    doc: dict[str, Any],
    existing_name: str | None,
    desired_item_code: str | None = None,
) -> dict[str, Any]:
    """Update `existing_name` if it still belongs to this Shopify entity, otherwise
    create fresh using `desired_item_code` (falls back to doc["item_code"]).

    `desired_item_code` must be passed whenever `existing_name` differs from the
    intended new item code (e.g. SKU changed), so collision recovery creates the
    right item instead of re-finding the colliding one."""
    name = existing_name
    collision = False

    if name is not None:
        live = erpnext_client.get_list(
            "Item",
            filters={"name": name},
            fields=["name", "shopify_variant_gid", "shopify_product_gid"],
        )
        if not live:
            name = None  # Item deleted externally — create fresh.
            collision = True
        else:
            expected_variant_gid = doc.get("shopify_variant_gid")
            expected_product_gid = doc.get("shopify_product_gid")
            actual = live[0]
            if expected_variant_gid and actual.get("shopify_variant_gid") not in (None, "", expected_variant_gid):
                name = None  # Collision: item belongs to a different variant.
                collision = True
            elif not expected_variant_gid and expected_product_gid and actual.get("shopify_product_gid") not in (None, "", expected_product_gid):
                name = None  # Collision: item belongs to a different product.
                collision = True

    fresh_item_code = desired_item_code or doc["item_code"]

    if name is None:
        # Always check by item_code before inserting — prevents DuplicateEntryError
        # from race conditions (two concurrent webhooks for the same new product)
        # and from the `collision` path where the item still physically exists.
        matches = erpnext_client.get_list("Item", filters={"item_code": fresh_item_code}, fields=["name"])
        if matches:
            name = matches[0]["name"]

    if name is not None:
        try:
            return erpnext_client.update({**doc, "doctype": "Item", "name": name})
        except Exception as e:
            # MySQL 1020 / Frappe QueryDeadlockError: the item's row is locked by
            # a concurrent DELETE transaction. Re-check whether it's truly gone.
            if not erpnext_client.get_list("Item", filters={"name": name}, fields=["name"]):
                raise ItemDeletedError(name) from e
            raise

    create_doc = {**doc, "item_code": fresh_item_code, "name": fresh_item_code}
    try:
        return erpnext_client.insert({**create_doc, "doctype": "Item"})
    except Exception as e:
        # Last-resort: INSERT lost a race — another request created the item
        # between our get_list check and the insert. Fall back to update.
        if "DuplicateEntryError" in str(e) or "Duplicate entry" in str(e):
            return erpnext_client.update({**doc, "doctype": "Item", "name": fresh_item_code})
        raise


def _get_synced_entity(session: Session, entity_type: EntityType, shopify_gid: str) -> SyncedEntity | None:
    statement = select(SyncedEntity).where(
        SyncedEntity.entity_type == entity_type,
        SyncedEntity.shopify_gid == shopify_gid,
    )
    return session.exec(statement).first()


def _save_synced_entity(session: Session, entity: SyncedEntity | None, **fields: Any) -> SyncedEntity:
    if entity is None:
        entity = SyncedEntity(**fields)
    else:
        for key, value in fields.items():
            setattr(entity, key, value)

    entity.last_synced_at = _utcnow()
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


def _gid(raw: dict[str, Any], resource: str = "Product") -> str:
    """A Shopify GraphQL GID, from a webhook payload, a `products/delete`
    payload (numeric `id` only, no `admin_graphql_api_id`), or a GraphQL
    response (`id` is already a GID)."""
    gid = raw.get("admin_graphql_api_id")
    if gid is not None:
        return str(gid)

    raw_id = raw.get("id")
    if raw_id is None:
        raise ValueError("Shopify object is missing 'id'/'admin_graphql_api_id'")
    if isinstance(raw_id, str) and raw_id.startswith("gid://"):
        return raw_id
    return f"gid://shopify/{resource}/{raw_id}"


def _raw_variants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    variants = payload.get("variants")
    if variants is None:
        return []
    if isinstance(variants, list):
        return variants
    return [edge["node"] for edge in variants.get("edges", [])]


def _is_simple_product(canonical_product: dict[str, Any], raw_variants: list[dict[str, Any]]) -> bool:
    """A product with only its single default variant maps to one non-variant Item."""
    if len(raw_variants) != 1:
        return False
    options = canonical_product["options"]
    return not options or all(option["name"] == "Title" for option in options)


def _variant_selected_options(raw_variant: dict[str, Any], product_options: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Normalize a variant's option selections to `[{"name": ..., "value": ...}]`.

    GraphQL variant nodes carry `selectedOptions` directly. Webhook variants
    only carry positional `option1`/`option2`/`option3` values, matched here
    against the sibling product's `options` (in `position` order) for names.
    """
    selected_options = raw_variant.get("selectedOptions")
    if selected_options is not None:
        return [{"name": option["name"], "value": option["value"]} for option in selected_options]

    selected = []
    for index, option in enumerate(product_options, start=1):
        value = raw_variant.get(f"option{index}")
        if value is not None:
            selected.append({"name": option["name"], "value": value})
    return selected
