from unittest.mock import MagicMock

from sqlmodel import select

from connector.models import EntityType, SyncedEntity
from connector.sync import entities
from connector.sync.products_to_shopify import handle_item_price_webhook, handle_item_webhook
from tests.erpnext.fakes import FakeERPNextClient
from tests.shopify.fakes import FakeShopifyClient

TEMPLATE_ITEM = {
    "doctype": "Item",
    "name": "snowboard",
    "item_code": "snowboard",
    "item_name": "Snowboard",
    "description": "<p>Good snowboard!</p>",
    "has_variants": 1,
    "variant_of": None,
    "sync_to_shopify": 1,
    "attributes": [{"attribute": "Size"}],
    "image": "",
}

VARIANT_SMALL = {
    "doctype": "Item",
    "name": "SB-S",
    "item_code": "SB-S",
    "item_name": "Small",
    "description": "",
    "has_variants": 0,
    "variant_of": "snowboard",
    "attributes": [{"attribute": "Size", "attribute_value": "Small"}],
    "image": "",
}

VARIANT_MEDIUM = {
    "doctype": "Item",
    "name": "SB-M",
    "item_code": "SB-M",
    "item_name": "Medium",
    "description": "",
    "has_variants": 0,
    "variant_of": "snowboard",
    "attributes": [{"attribute": "Size", "attribute_value": "Medium"}],
    "image": "",
}


def _synced_catalog(session):
    """A template Item with two already-synced variants, per issue 05's flow
    but driven ERPNext-side (issue 07): one webhook call per Item."""
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    template = client.insert(dict(TEMPLATE_ITEM))
    variant_small = client.insert(dict(VARIANT_SMALL))
    variant_medium = client.insert(dict(VARIANT_MEDIUM))

    handle_item_webhook(session, shopify, client, template)
    handle_item_webhook(session, shopify, client, variant_small)
    handle_item_webhook(session, shopify, client, variant_medium)

    product_gid = template["shopify_product_gid"]
    return client, shopify, template, variant_small, variant_medium, product_gid


def test_new_template_creates_shopify_product_with_options(session):
    client, shopify, template, variant_small, variant_medium, product_gid = _synced_catalog(session)

    create_calls = [c for c in shopify.calls if c[0] == "create_product"]
    assert len(create_calls) == 1
    product_input = create_calls[0][1]["product_input"]
    assert product_input["title"] == "Snowboard"
    assert product_input["descriptionHtml"] == "<p>Good snowboard!</p>"
    assert product_input["productOptions"] == [
        {"name": "Size", "values": [{"name": "Small"}, {"name": "Medium"}]}
    ]

    assert template["shopify_product_gid"] == product_gid
    assert variant_small["shopify_variant_gid"]
    assert variant_medium["shopify_variant_gid"]

    rows = session.exec(select(SyncedEntity)).all()
    template_entity = next(e for e in rows if e.entity_type == EntityType.PRODUCT)
    variant_entities = [e for e in rows if e.entity_type == EntityType.VARIANT]
    assert template_entity.erpnext_name == "snowboard"
    assert template_entity.shopify_gid == product_gid
    assert len(variant_entities) == 2
    assert all(e.group_key == product_gid for e in variant_entities)
    assert all(e.shopify_fingerprint == e.erpnext_fingerprint for e in rows)


def test_unsynced_item_and_variant_are_skipped(session):
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    template = client.insert(
        {
            "doctype": "Item",
            "name": "gadget",
            "item_code": "gadget",
            "item_name": "Gadget",
            "description": "",
            "has_variants": 1,
            "variant_of": None,
            "sync_to_shopify": 0,
            "attributes": [{"attribute": "Color"}],
            "image": "",
        }
    )
    variant = client.insert(
        {
            "doctype": "Item",
            "name": "gadget-red",
            "item_code": "gadget-red",
            "item_name": "Gadget Red",
            "description": "",
            "has_variants": 0,
            "variant_of": "gadget",
            "attributes": [{"attribute": "Color", "attribute_value": "Red"}],
            "image": "",
        }
    )

    handle_item_webhook(session, shopify, client, template)
    handle_item_webhook(session, shopify, client, variant)

    assert shopify.calls == []
    assert session.exec(select(SyncedEntity)).all() == []


def test_echo_for_unchanged_template_makes_no_shopify_calls(session):
    client, shopify, template, variant_small, variant_medium, product_gid = _synced_catalog(session)

    spy = MagicMock(wraps=shopify)
    handle_item_webhook(session, spy, client, template)

    spy.create_product.assert_not_called()
    spy.update_product.assert_not_called()
    spy.create_variants.assert_not_called()


def test_title_and_description_update_updates_shopify_product(session):
    client, shopify, template, variant_small, variant_medium, product_gid = _synced_catalog(session)

    updated = dict(template)
    updated["item_name"] = "Snowboard Pro"
    updated["description"] = "<p>An even better snowboard!</p>"

    spy = MagicMock(wraps=shopify)
    handle_item_webhook(session, spy, client, updated)

    spy.create_product.assert_not_called()
    spy.update_product.assert_called_once()
    args, _ = spy.update_product.call_args
    assert args[0] == product_gid
    assert args[1]["title"] == "Snowboard Pro"
    assert args[1]["descriptionHtml"] == "<p>An even better snowboard!</p>"

    entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", "snowboard")
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_new_variant_on_existing_template_creates_variant(session):
    client, shopify, template, variant_small, variant_medium, product_gid = _synced_catalog(session)

    variant_large = client.insert(
        {
            "doctype": "Item",
            "name": "SB-L",
            "item_code": "SB-L",
            "item_name": "Large",
            "description": "",
            "has_variants": 0,
            "variant_of": "snowboard",
            "attributes": [{"attribute": "Size", "attribute_value": "Large"}],
            "image": "",
        }
    )

    handle_item_webhook(session, shopify, client, variant_large)

    method, kwargs = shopify.calls[-1]
    assert method == "create_variants"
    assert kwargs["product_gid"] == product_gid
    assert kwargs["variants"] == [{"sku": "SB-L", "optionValues": [{"name": "Large", "optionName": "Size"}]}]

    assert client.get_doc("Item", "SB-L")["shopify_variant_gid"]

    entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", "SB-L")
    assert entity is not None
    assert entity.group_key == product_gid


def test_new_simple_item_creates_shopify_product_with_default_variant(session):
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    item = client.insert(
        {
            "doctype": "Item",
            "name": "widget",
            "item_code": "widget",
            "item_name": "Widget",
            "description": "<p>A widget</p>",
            "has_variants": 0,
            "variant_of": None,
            "sync_to_shopify": 1,
            "attributes": [],
            "image": "",
        }
    )
    client.insert(
        {
            "doctype": "Item Price",
            "name": "IP-W",
            "item_code": "widget",
            "price_list": "Standard Selling",
            "price_list_rate": 9.99,
        }
    )

    handle_item_webhook(session, shopify, client, item)

    create_calls = [c for c in shopify.calls if c[0] == "create_product"]
    assert len(create_calls) == 1
    product_input = create_calls[0][1]["product_input"]
    assert product_input["title"] == "Widget"
    assert product_input["variants"] == [{"sku": "widget", "price": "9.99"}]

    doc = client.get_doc("Item", "widget")
    assert doc["shopify_product_gid"]
    assert doc["shopify_variant_gid"]

    entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", "widget")
    assert entity.shopify_gid == doc["shopify_product_gid"]
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_item_price_change_updates_shopify_variant_price(session):
    client, shopify, template, variant_small, variant_medium, product_gid = _synced_catalog(session)

    client.insert(
        {
            "doctype": "Item Price",
            "name": "IP-SB-S",
            "item_code": "SB-S",
            "price_list": "Standard Selling",
            "price_list_rate": 120.0,
        }
    )

    payload = {"doctype": "Item Price", "price_list": "Standard Selling", "item_code": "SB-S", "price_list_rate": 120.0}
    handle_item_price_webhook(session, shopify, client, payload)

    price_calls = [c for c in shopify.calls if c[0] == "update_variant_price"]
    assert len(price_calls) == 1
    _, kwargs = price_calls[0]
    assert kwargs["product_gid"] == product_gid
    assert kwargs["variant_gid"] == variant_small["shopify_variant_gid"]
    assert kwargs["price"] == "120.00"

    entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", "SB-S")
    assert entity.erpnext_fingerprint == entity.shopify_fingerprint


def test_item_price_echo_makes_no_shopify_calls(session):
    client, shopify, template, variant_small, variant_medium, product_gid = _synced_catalog(session)

    client.insert(
        {
            "doctype": "Item Price",
            "name": "IP-SB-S",
            "item_code": "SB-S",
            "price_list": "Standard Selling",
            "price_list_rate": 120.0,
        }
    )
    payload = {"doctype": "Item Price", "price_list": "Standard Selling", "item_code": "SB-S", "price_list_rate": 120.0}
    handle_item_price_webhook(session, shopify, client, payload)

    spy = MagicMock(wraps=shopify)
    handle_item_price_webhook(session, spy, client, payload)

    spy.update_variant_price.assert_not_called()


def test_item_price_for_unsynced_item_is_skipped(session):
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    client.insert(
        {
            "doctype": "Item",
            "name": "widget",
            "item_code": "widget",
            "item_name": "Widget",
            "description": "",
            "has_variants": 0,
            "variant_of": None,
            "sync_to_shopify": 0,
            "attributes": [],
            "image": "",
        }
    )
    client.insert(
        {
            "doctype": "Item Price",
            "name": "IP-W",
            "item_code": "widget",
            "price_list": "Standard Selling",
            "price_list_rate": 50.0,
        }
    )

    payload = {"doctype": "Item Price", "price_list": "Standard Selling", "item_code": "widget", "price_list_rate": 50.0}
    handle_item_price_webhook(session, shopify, client, payload)

    assert shopify.calls == []
