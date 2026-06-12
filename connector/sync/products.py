"""Shopify product/variant -> ERPNext Item sync (issue 05).

Handles the `products/create` and `products/update` webhook topics: Echo
detection (per ADR-0003) against the stored `shopify_fingerprint`, then
create/update of the corresponding ERPNext template + variant Items (or a
single non-variant Item for single-variant products), per the PRD's
Product & Variant mapping.
"""

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncedEntity

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

    if _is_simple_product(canonical_product, raw_variants):
        _sync_simple_product(
            session, erpnext_client, payload, product_gid, canonical_product, product_fingerprint, raw_variants[0]
        )
        return

    _sync_template_product(
        session, erpnext_client, payload, product_gid, canonical_product, product_fingerprint, raw_variants
    )


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
    """Disable the ERPNext Item(s) for an archived/deleted Shopify product.

    Looks up the Synced Entity for the product's `shopify_product_gid` and
    disables its template Item and all variant Items, without deleting them.
    A product with no Synced Entity (never synced) is a no-op.
    """
    product_gid = _gid(payload)

    template_entity = _get_synced_entity(session, EntityType.PRODUCT, product_gid)
    if template_entity is None:
        return

    _disable_item_if_needed(session, erpnext_client, template_entity)
    for variant_entity in _get_variant_entities(session, product_gid):
        _disable_item_if_needed(session, erpnext_client, variant_entity)


def _disable_item_if_needed(session: Session, erpnext_client: ERPNextClientProtocol, entity: SyncedEntity) -> None:
    if entity.erpnext_name is None:
        return

    item = erpnext_client.get_doc("Item", entity.erpnext_name)
    if item.get("disabled"):
        return  # Echo: already disabled, no redundant write.

    erpnext_client.set_value("Item", entity.erpnext_name, "disabled", 1)
    entity.last_synced_at = _utcnow()
    session.add(entity)
    session.commit()


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
    template_item_code = payload.get("handle") or product_gid

    if template_entity is None or template_entity.shopify_fingerprint != product_fingerprint:
        _ensure_item_attributes(erpnext_client, canonical_product["options"])
        template_doc = _build_template_doc(template_item_code, canonical_product, product_gid)
        existing_name = template_entity.erpnext_name if template_entity else None
        result = _upsert_item(erpnext_client, template_doc, existing_name)

        template_entity = _save_synced_entity(
            session,
            template_entity,
            entity_type=EntityType.PRODUCT,
            shopify_gid=product_gid,
            group_key=product_gid,
            erpnext_doctype="Item",
            erpnext_name=result["name"],
            shopify_fingerprint=product_fingerprint,
            erpnext_fingerprint=product_fingerprint,
        )
        _sync_product_images(erpnext_client, result["name"], canonical_product)

    for raw_variant in raw_variants:
        _sync_variant(session, erpnext_client, raw_variant, canonical_product["options"], product_gid, template_entity.erpnext_name)


def _sync_variant(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    raw_variant: dict[str, Any],
    product_options: list[dict[str, Any]],
    product_gid: str,
    template_item_code: str,
) -> None:
    variant_gid = _gid(raw_variant, resource="ProductVariant")
    selected_options = _variant_selected_options(raw_variant, product_options)
    canonical_variant = canonicalize(EntityType.VARIANT, {**raw_variant, "selected_options": selected_options})
    variant_fingerprint = fingerprint(canonical_variant)

    variant_entity = _get_synced_entity(session, EntityType.VARIANT, variant_gid)
    if variant_entity is not None and variant_entity.shopify_fingerprint == variant_fingerprint:
        return  # Echo: this variant's tracked fields haven't changed.

    item_code = canonical_variant["sku"] or variant_gid
    variant_doc = _build_variant_doc(item_code, template_item_code, canonical_variant, product_gid, variant_gid)
    existing_name = variant_entity.erpnext_name if variant_entity else None
    result = _upsert_item(erpnext_client, variant_doc, existing_name)

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

    item_code = sku or payload.get("handle") or product_gid
    doc = {
        "name": item_code,
        "item_code": item_code,
        "item_name": canonical_product["title"],
        "description": canonical_product["description"],
        "item_group": DEFAULT_ITEM_GROUP,
        "stock_uom": DEFAULT_STOCK_UOM,
        "has_variants": 0,
        "shopify_product_gid": product_gid,
        "shopify_variant_gid": variant_gid,
        "image": canonical_product.get("featured_image", ""),
    }
    existing_name = entity.erpnext_name if entity else None
    result = _upsert_item(erpnext_client, doc, existing_name)

    _sync_variant_price(erpnext_client, result["name"], raw_variant.get("price"))

    _save_synced_entity(
        session,
        entity,
        entity_type=EntityType.PRODUCT,
        shopify_gid=product_gid,
        group_key=product_gid,
        erpnext_doctype="Item",
        erpnext_name=result["name"],
        shopify_fingerprint=item_fingerprint,
        erpnext_fingerprint=item_fingerprint,
    )
    _sync_product_images(erpnext_client, result["name"], canonical_product)


def _build_template_doc(item_code: str, canonical_product: dict[str, Any], product_gid: str) -> dict[str, Any]:
    return {
        "name": item_code,
        "item_code": item_code,
        "item_name": canonical_product["title"],
        "description": canonical_product["description"],
        "item_group": DEFAULT_ITEM_GROUP,
        "stock_uom": DEFAULT_STOCK_UOM,
        "has_variants": 1,
        "attributes": [{"attribute": option["name"]} for option in canonical_product["options"]],
        "shopify_product_gid": product_gid,
        # Featured image -> Item `image` field (issue 08); "" when absent.
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
    }


def _ensure_item_attributes(erpnext_client: ERPNextClientProtocol, options: list[dict[str, Any]]) -> None:
    """Create any "Item Attribute" doctype docs the template Item references."""
    for option in options:
        existing = erpnext_client.get_list("Item Attribute", filters={"name": option["name"]}, fields=["name"])
        if existing:
            continue
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


def _upsert_item(erpnext_client: ERPNextClientProtocol, doc: dict[str, Any], existing_name: str | None) -> dict[str, Any]:
    name = existing_name
    if name is None:
        # SKU (item_code) is the join key for items not yet tracked by a Synced Entity.
        matches = erpnext_client.get_list("Item", filters={"item_code": doc["item_code"]}, fields=["name"])
        if matches:
            name = matches[0]["name"]

    if name is not None:
        return erpnext_client.update({**doc, "doctype": "Item", "name": name})

    return erpnext_client.insert({**doc, "doctype": "Item"})


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
