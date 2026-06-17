import copy

import pytest

from connector.fingerprint import canonicalize, fingerprint

WEBHOOK_PRODUCT = {
    "id": 1071559771,
    "admin_graphql_api_id": "gid://shopify/Product/1071559771",
    "title": "Burton Custom Freestyle 151",
    "body_html": "<p>Good snowboard!</p>",
    "vendor": "Burton",
    "product_type": "Snowboard",
    "handle": "burton-custom-freestyle-151",
    "created_at": "2024-01-01T00:00:00-05:00",
    "updated_at": "2024-01-02T00:00:00-05:00",
    "options": [
        {"id": 1, "product_id": 1071559771, "name": "Size", "position": 1, "values": ["Small", "Medium", "Large"]},
    ],
    "variants": [
        {
            "id": 1,
            "admin_graphql_api_id": "gid://shopify/ProductVariant/1",
            "title": "Small",
            "price": "100.00",
            "sku": "SB-S",
            "position": 1,
            "option1": "Small",
            "option2": None,
            "option3": None,
            "updated_at": "2024-01-02T00:00:00-05:00",
        },
    ],
}

GRAPHQL_PRODUCT = {
    "id": "gid://shopify/Product/1071559771",
    "title": "Burton Custom Freestyle 151",
    "descriptionHtml": "<p>Good snowboard!</p>",
    "vendor": "Burton",
    "productType": "Snowboard",
    "tags": [],
    "status": "ACTIVE",
    "handle": "burton-custom-freestyle-151",
    "updatedAt": "2024-01-02T00:00:00Z",
    "options": [
        {"id": "gid://shopify/ProductOption/1", "name": "Size", "position": 1, "values": ["Small", "Medium", "Large"]},
    ],
    "variants": {
        "edges": [
            {
                "node": {
                    "id": "gid://shopify/ProductVariant/1",
                    "title": "Small",
                    "price": "100.00",
                    "sku": "SB-S",
                    "selectedOptions": [{"name": "Size", "value": "Small"}],
                    "updatedAt": "2024-01-02T00:00:00Z",
                }
            },
        ],
    },
}

WEBHOOK_VARIANT_NORMALIZED = {
    "sku": "SB-S",
    "title": "Small",
    "selected_options": [{"name": "Size", "value": "Small"}],
}

GRAPHQL_VARIANT = {
    "id": "gid://shopify/ProductVariant/1",
    "title": "Small",
    "price": "100.00",
    "sku": "SB-S",
    "selectedOptions": [{"name": "Size", "value": "Small"}],
    "updatedAt": "2024-01-02T00:00:00Z",
}


def test_canonicalize_product_webhook_and_graphql_match():
    webhook_canonical = canonicalize("product", WEBHOOK_PRODUCT)
    graphql_canonical = canonicalize("product", GRAPHQL_PRODUCT)

    assert webhook_canonical == graphql_canonical
    assert webhook_canonical == {
        "title": "Burton Custom Freestyle 151",
        "description": "<p>Good snowboard!</p>",
        "options": [{"name": "Size", "values": ["Small", "Medium", "Large"]}],
        "vendor": "Burton",
        "product_type": "Snowboard",
        "tags": [],
        "status": "ACTIVE",
        "featured_image": "",
        "media": [],
    }
    assert fingerprint(webhook_canonical) == fingerprint(graphql_canonical)


def test_canonicalize_variant_webhook_and_graphql_match():
    # WEBHOOK_VARIANT_NORMALIZED omits price; GRAPHQL_VARIANT carries it. Add a
    # matching price so the two shapes canonicalize identically.
    webhook_canonical = canonicalize("variant", {**WEBHOOK_VARIANT_NORMALIZED, "price": "100.00"})
    graphql_canonical = canonicalize("variant", GRAPHQL_VARIANT)

    assert webhook_canonical == graphql_canonical
    assert webhook_canonical == {
        "sku": "SB-S",
        "title": "Small",
        "selected_options": [{"name": "Size", "value": "Small"}],
        "price": "100.00",
        "image": "",
    }
    assert fingerprint(webhook_canonical) == fingerprint(graphql_canonical)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.__setitem__("updated_at", "2099-12-31T00:00:00-05:00"),
        lambda raw: raw.__setitem__("handle", "a-different-handle"),
    ],
)
def test_product_fingerprint_unchanged_by_untracked_fields(mutate):
    original = canonicalize("product", WEBHOOK_PRODUCT)

    mutated = copy.deepcopy(WEBHOOK_PRODUCT)
    mutate(mutated)

    assert fingerprint(canonicalize("product", mutated)) == fingerprint(original)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.__setitem__("title", "A Different Title"),
        lambda raw: raw.__setitem__("body_html", "<p>Different description</p>"),
        lambda raw: raw.__setitem__(
            "options",
            [{"id": 1, "product_id": 1071559771, "name": "Size", "position": 1, "values": ["Small", "Large"]}],
        ),
        lambda raw: raw.__setitem__("vendor", "A Different Vendor"),
        lambda raw: raw.__setitem__("product_type", "Different Type"),
        lambda raw: raw.__setitem__("status", "draft"),
    ],
)
def test_product_fingerprint_changes_for_tracked_fields(mutate):
    original = canonicalize("product", WEBHOOK_PRODUCT)

    mutated = copy.deepcopy(WEBHOOK_PRODUCT)
    mutate(mutated)

    assert fingerprint(canonicalize("product", mutated)) != fingerprint(original)


def test_variant_fingerprint_unchanged_by_untracked_fields():
    original = canonicalize("variant", GRAPHQL_VARIANT)

    mutated = copy.deepcopy(GRAPHQL_VARIANT)
    mutated["updatedAt"] = "2099-12-31T00:00:00Z"
    mutated["inventoryQuantity"] = 42

    assert fingerprint(canonicalize("variant", mutated)) == fingerprint(original)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.__setitem__("sku", "SB-DIFFERENT"),
        lambda raw: raw.__setitem__("selectedOptions", [{"name": "Size", "value": "Large"}]),
        # Price is tracked per issue 10 (Shopify variant price -> ERPNext Item Price).
        lambda raw: raw.__setitem__("price", "999.00"),
    ],
)
def test_variant_fingerprint_changes_for_tracked_fields(mutate):
    original = canonicalize("variant", GRAPHQL_VARIANT)

    mutated = copy.deepcopy(GRAPHQL_VARIANT)
    mutate(mutated)

    assert fingerprint(canonicalize("variant", mutated)) != fingerprint(original)


def test_canonicalize_unsupported_entity_type_raises():
    # `image` is a declared EntityType but has no registered canonicalizer
    # (image data rides along on the `product` entity, per issues 08/09).
    with pytest.raises(ValueError):
        canonicalize("image", {})
