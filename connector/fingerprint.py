"""Canonicalization and Fingerprint computation (per ADR-0003).

A Fingerprint is a SHA256 hash of a canonical JSON object containing only the
fields this Connector tracks for a given `entity_type`. `canonicalize` must
produce identical output for the same underlying entity regardless of whether
`raw_data` came from a Shopify webhook payload, a Shopify GraphQL query, or an
ERPNext REST response — this is the safety-critical property Echo detection
depends on.

Each `entity_type` has one canonicalizer, registered in `CANONICALIZERS` so the
recurring reconciliation pass (issue 14) can recompute any row's Fingerprint
generically, without knowing the concrete type.
"""

import hashlib
import json
from typing import Any, Callable

from connector.models import EntityType

CanonicalDict = dict[str, Any]


def canonicalize(entity_type: EntityType | str, raw_data: dict[str, Any]) -> CanonicalDict:
    """Extract the tracked fields for `entity_type` from `raw_data`."""
    key = EntityType(entity_type)
    try:
        canonicalizer = CANONICALIZERS[key]
    except KeyError:
        raise ValueError(f"Unsupported entity_type for canonicalize: {entity_type!r}") from None
    return canonicalizer(raw_data)


def fingerprint(canonical: CanonicalDict) -> str:
    """SHA256 hex digest of a canonical dict's JSON form."""
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _money(value: Any) -> str:
    """Normalize a price to a 2-decimal string so `"20.0"`, `20`, and `"20.00"`
    (Shopify strings vs ERPNext floats) produce the same Fingerprint."""
    if value is None or value == "":
        return ""
    return f"{float(value):.2f}"


def _image_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """Featured image URL + the ordered list of all media URLs.

    Tolerates the three shapes the Connector sees: Shopify GraphQL
    (`featuredImage.url`, `media.edges[].node...`), the Shopify webhook/REST
    payload (`image.src`, `images[].src`), and the ERPNext-side normalized form
    the handlers build (`featured_image` string, `media` list of strings)."""
    featured = ""
    if isinstance(raw.get("featured_image"), str):
        featured = raw["featured_image"]
    elif isinstance(raw.get("featuredImage"), dict):
        featured = raw["featuredImage"].get("url") or ""
    elif isinstance(raw.get("image"), dict):
        featured = raw["image"].get("src") or ""
    elif isinstance(raw.get("image"), str):
        featured = raw["image"]

    media: list[str] = []
    if isinstance(raw.get("media"), list) and all(isinstance(m, str) for m in raw["media"]):
        media = list(raw["media"])
    elif isinstance(raw.get("media"), dict):  # GraphQL connection
        for edge in raw["media"].get("edges", []):
            node = edge.get("node", {})
            image = node.get("image") or (node.get("preview") or {}).get("image") or {}
            url = image.get("url") or image.get("src")
            if url:
                media.append(url)
    elif isinstance(raw.get("images"), list):  # webhook/REST
        for image in raw["images"]:
            url = image.get("src") if isinstance(image, dict) else image
            if url:
                media.append(url)

    return {"featured_image": featured, "media": media}


def _canonicalize_product(raw: dict[str, Any]) -> CanonicalDict:
    title = raw.get("title") or ""

    # Shopify GraphQL uses `descriptionHtml`; the webhook/REST payload uses `body_html`.
    description = raw.get("descriptionHtml")
    if description is None:
        description = raw.get("body_html")
    description = description or ""

    options = [
        {"name": option.get("name", ""), "values": list(option.get("values") or [])}
        for option in raw.get("options") or []
    ]

    return {"title": title, "description": description, "options": options, **_image_fields(raw)}


def _canonicalize_variant(raw: dict[str, Any]) -> CanonicalDict:
    sku = raw.get("sku") or ""
    title = raw.get("title") or ""

    # Shopify GraphQL variant nodes carry `selectedOptions` directly. Webhook
    # variants only carry positional `option1`/`option2`/`option3` values, so
    # the sync handler normalizes those to `selected_options` (using the
    # sibling product's `options` for names) before calling canonicalize.
    selected_options = raw.get("selectedOptions")
    if selected_options is None:
        selected_options = raw.get("selected_options") or []

    normalized_options = sorted(
        ({"name": option.get("name", ""), "value": option.get("value", "")} for option in selected_options),
        key=lambda option: option["name"],
    )

    # Price: Shopify variants carry `price` (string); the ERPNext-side handler
    # passes the Item Price's `price_list_rate` under `price` as well.
    return {
        "sku": sku,
        "title": title,
        "selected_options": normalized_options,
        "price": _money(raw.get("price")),
    }


def _address(raw: dict[str, Any]) -> dict[str, str]:
    return {
        "address1": raw.get("address1") or raw.get("address_line1") or "",
        "address2": raw.get("address2") or raw.get("address_line2") or "",
        "city": raw.get("city") or "",
        "province": raw.get("province") or raw.get("state") or "",
        "country": raw.get("country") or "",
        "zip": raw.get("zip") or raw.get("pincode") or "",
    }


def _canonicalize_customer(raw: dict[str, Any]) -> CanonicalDict:
    """Tracks name, email, phone, addresses across Shopify and ERPNext shapes."""
    # Name: Shopify GraphQL `firstName`/`lastName`, webhook `first_name`/
    # `last_name`, ERPNext `customer_name`.
    name = raw.get("customer_name")
    if not name:
        first = raw.get("firstName") or raw.get("first_name") or ""
        last = raw.get("lastName") or raw.get("last_name") or ""
        name = " ".join(part for part in (first, last) if part)
    name = name or ""

    email = raw.get("email") or raw.get("email_id") or ""
    phone = raw.get("phone") or raw.get("mobile_no") or ""

    raw_addresses = raw.get("addresses")
    if not raw_addresses:
        default = raw.get("defaultAddress") or raw.get("default_address")
        raw_addresses = [default] if default else []
    addresses = sorted(
        (_address(addr) for addr in raw_addresses if addr),
        key=lambda a: json.dumps(a, sort_keys=True),
    )

    return {"name": name, "email": email, "phone": phone, "addresses": addresses}


def _order_line_items(raw: dict[str, Any]) -> list[dict[str, Any]]:
    line_items = raw.get("line_items")
    if isinstance(line_items, dict):  # GraphQL connection
        line_items = [edge["node"] for edge in line_items.get("edges", [])]
    line_items = line_items or []

    normalized = []
    for line in line_items:
        variant = line.get("variant") or {}
        variant_gid = (
            line.get("variant_gid")
            or variant.get("id")
            or line.get("admin_graphql_api_id")
        )
        if variant_gid is None and line.get("variant_id") is not None:
            variant_gid = f"gid://shopify/ProductVariant/{line['variant_id']}"
        normalized.append(
            {
                "variant_gid": variant_gid or "",
                "quantity": int(line.get("quantity") or 0),
                "price": _money(line.get("price")),
            }
        )
    return sorted(normalized, key=lambda line: (line["variant_gid"], line["price"]))


def _canonicalize_order(raw: dict[str, Any]) -> CanonicalDict:
    """Tracks line items, taxes, shipping, discounts, and totals."""
    shipping = raw.get("total_shipping_price") or raw.get("total_shipping")
    if shipping is None:
        shipping_set = raw.get("total_shipping_price_set") or {}
        shipping = (shipping_set.get("shop_money") or {}).get("amount")

    return {
        "line_items": _order_line_items(raw),
        "tax": _money(raw.get("total_tax")),
        "shipping": _money(shipping),
        "discount": _money(raw.get("total_discounts")),
        "total": _money(raw.get("total_price")),
    }


def _canonicalize_inventory_level(raw: dict[str, Any]) -> CanonicalDict:
    """Keyed on the absolute available quantity at the configured Location/Warehouse."""
    available = raw.get("available")
    if available is None:
        available = raw.get("actual_qty")
    return {"available": int(available) if available is not None else 0}


def _canonicalize_fulfillment(raw: dict[str, Any]) -> CanonicalDict:
    """Tracks which line items/quantities of an Order have been fulfilled."""
    line_items = raw.get("line_items")
    if isinstance(line_items, dict):
        line_items = [edge["node"] for edge in line_items.get("edges", [])]
    line_items = line_items or []

    normalized = []
    for line in line_items:
        variant = line.get("variant") or {}
        variant_gid = line.get("variant_gid") or variant.get("id")
        if variant_gid is None and line.get("variant_id") is not None:
            variant_gid = f"gid://shopify/ProductVariant/{line['variant_id']}"
        normalized.append(
            {"variant_gid": variant_gid or "", "quantity": int(line.get("quantity") or 0)}
        )
    return {"line_items": sorted(normalized, key=lambda line: line["variant_gid"])}


CANONICALIZERS: dict[EntityType, Callable[[dict[str, Any]], CanonicalDict]] = {
    EntityType.PRODUCT: _canonicalize_product,
    EntityType.VARIANT: _canonicalize_variant,
    EntityType.CUSTOMER: _canonicalize_customer,
    EntityType.ORDER: _canonicalize_order,
    EntityType.INVENTORY_LEVEL: _canonicalize_inventory_level,
    EntityType.FULFILLMENT: _canonicalize_fulfillment,
}
