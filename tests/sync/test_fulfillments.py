from unittest.mock import MagicMock

from connector.models import EntityType
from connector.sync import entities
from connector.sync.fulfillments import handle_delivery_note_submit, handle_shopify_fulfillment_webhook
from tests.erpnext.fakes import FakeERPNextClient
from tests.shopify.fakes import FakeShopifyClient

VARIANT_GID = "gid://shopify/ProductVariant/10"
ITEM_CODE = "TEE-001"
ORDER_GID = "gid://shopify/Order/100"
SO_NAME = "SO-0001"


def _seed_variant(session):
    entities.save(
        session,
        None,
        entity_type=EntityType.VARIANT,
        shopify_gid=VARIANT_GID,
        group_key="gid://shopify/Product/1",
        erpnext_doctype="Item",
        erpnext_name=ITEM_CODE,
        shopify_fingerprint="seed",
        erpnext_fingerprint="seed",
    )


def _seed_order(session):
    entities.save(
        session,
        None,
        entity_type=EntityType.ORDER,
        shopify_gid=ORDER_GID,
        group_key=ORDER_GID,
        erpnext_doctype="Sales Order",
        erpnext_name=SO_NAME,
        shopify_fingerprint="seed",
        erpnext_fingerprint="seed",
    )


# --- Issue 19: ERPNext Delivery Note -> Shopify fulfillmentCreate ---


def test_delivery_note_submit_creates_shopify_fulfillment(session):
    _seed_variant(session)
    _seed_order(session)
    erpnext_client = FakeERPNextClient()
    dn = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "name": "DN-0001",
            "against_sales_order": SO_NAME,
            "items": [{"item_code": ITEM_CODE, "qty": 2, "against_sales_order": SO_NAME}],
        }
    )
    erpnext_client.submit(dn)
    shopify_client = FakeShopifyClient()

    handle_delivery_note_submit(session, shopify_client, erpnext_client, dn)

    create_calls = [c for c in shopify_client.calls if c[0] == "create_fulfillment"]
    assert len(create_calls) == 1
    assert create_calls[0][1]["fulfillment_input"] == {
        "orderId": ORDER_GID,
        "lineItems": [{"variantId": VARIANT_GID, "quantity": 2}],
    }

    fulfillment_gid = next(iter(shopify_client.fulfillments))
    assert erpnext_client.get_doc("Delivery Note", "DN-0001")["shopify_fulfillment_gid"] == fulfillment_gid

    entity = entities.get_by_shopify_gid(session, EntityType.FULFILLMENT, fulfillment_gid)
    assert entity is not None
    assert entity.group_key == ORDER_GID
    assert entity.erpnext_doctype == "Delivery Note"
    assert entity.erpnext_name == "DN-0001"
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_delivery_note_submit_returns_early_without_order_entity(session):
    _seed_variant(session)
    erpnext_client = FakeERPNextClient()
    dn = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "name": "DN-0001",
            "against_sales_order": SO_NAME,
            "items": [{"item_code": ITEM_CODE, "qty": 2, "against_sales_order": SO_NAME}],
        }
    )
    erpnext_client.submit(dn)
    shopify_client = FakeShopifyClient()

    handle_delivery_note_submit(session, shopify_client, erpnext_client, dn)

    assert shopify_client.calls == []
    assert entities.get_group(session, ORDER_GID, EntityType.FULFILLMENT) == []


def test_delivery_note_redelivery_is_echo_safe(session):
    _seed_variant(session)
    _seed_order(session)
    erpnext_client = FakeERPNextClient()
    dn = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "name": "DN-0001",
            "against_sales_order": SO_NAME,
            "items": [{"item_code": ITEM_CODE, "qty": 2, "against_sales_order": SO_NAME}],
        }
    )
    erpnext_client.submit(dn)
    shopify_client = FakeShopifyClient()
    handle_delivery_note_submit(session, shopify_client, erpnext_client, dn)

    spy = MagicMock(wraps=shopify_client)
    handle_delivery_note_submit(session, spy, erpnext_client, erpnext_client.get_doc("Delivery Note", "DN-0001"))

    spy.create_fulfillment.assert_not_called()


def test_partial_then_full_fulfillment_creates_separate_shopify_fulfillments(session):
    _seed_variant(session)
    _seed_order(session)
    erpnext_client = FakeERPNextClient()
    shopify_client = FakeShopifyClient()

    dn1 = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "name": "DN-0001",
            "against_sales_order": SO_NAME,
            "items": [{"item_code": ITEM_CODE, "qty": 1, "against_sales_order": SO_NAME}],
        }
    )
    erpnext_client.submit(dn1)
    handle_delivery_note_submit(session, shopify_client, erpnext_client, dn1)

    dn2 = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "name": "DN-0002",
            "against_sales_order": SO_NAME,
            "items": [{"item_code": ITEM_CODE, "qty": 2, "against_sales_order": SO_NAME}],
        }
    )
    erpnext_client.submit(dn2)
    handle_delivery_note_submit(session, shopify_client, erpnext_client, dn2)

    create_calls = [c for c in shopify_client.calls if c[0] == "create_fulfillment"]
    assert len(create_calls) == 2
    assert create_calls[0][1]["fulfillment_input"]["lineItems"] == [{"variantId": VARIANT_GID, "quantity": 1}]
    assert create_calls[1][1]["fulfillment_input"]["lineItems"] == [{"variantId": VARIANT_GID, "quantity": 2}]

    group = entities.get_group(session, ORDER_GID, EntityType.FULFILLMENT)
    assert len(group) == 1
    assert group[0].erpnext_name == "DN-0002"


# --- Issue 20: Shopify fulfillment -> ERPNext Delivery Note ---


FULFILLMENT_PAYLOAD = {
    "id": 1,
    "admin_graphql_api_id": "gid://shopify/Fulfillment/1",
    "order_id": 100,
    "line_items": [{"variant_id": 10, "quantity": 2}],
}


def test_shopify_fulfillment_creates_delivery_note(session):
    _seed_variant(session)
    _seed_order(session)
    erpnext_client = FakeERPNextClient()
    erpnext_client.insert({"doctype": "Sales Order", "name": SO_NAME, "customer": "Guest"})

    handle_shopify_fulfillment_webhook(session, erpnext_client, FULFILLMENT_PAYLOAD)

    delivery_notes = erpnext_client.get_list("Delivery Note")
    assert len(delivery_notes) == 1
    dn = delivery_notes[0]
    assert dn["customer"] == "Guest"
    assert dn["against_sales_order"] == SO_NAME
    assert dn["shopify_fulfillment_gid"] == "gid://shopify/Fulfillment/1"
    assert dn["items"] == [{"item_code": ITEM_CODE, "qty": 2, "against_sales_order": SO_NAME}]
    assert dn["docstatus"] == 1

    entity = entities.get_by_shopify_gid(session, EntityType.FULFILLMENT, "gid://shopify/Fulfillment/1")
    assert entity is not None
    assert entity.group_key == ORDER_GID
    assert entity.erpnext_doctype == "Delivery Note"
    assert entity.erpnext_name == dn["name"]
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_shopify_fulfillment_returns_early_without_order_entity(session):
    _seed_variant(session)
    erpnext_client = FakeERPNextClient()

    handle_shopify_fulfillment_webhook(session, erpnext_client, FULFILLMENT_PAYLOAD)

    assert erpnext_client.get_list("Delivery Note") == []


def test_shopify_fulfillment_is_echo_for_connectors_own_delivery_note(session):
    """A fulfillment webhook for the Delivery Note the Connector just created
    via issue 19 must not create a duplicate Delivery Note."""
    _seed_variant(session)
    _seed_order(session)
    erpnext_client = FakeERPNextClient()
    dn = erpnext_client.insert(
        {
            "doctype": "Delivery Note",
            "name": "DN-0001",
            "against_sales_order": SO_NAME,
            "items": [{"item_code": ITEM_CODE, "qty": 2, "against_sales_order": SO_NAME}],
        }
    )
    erpnext_client.submit(dn)
    shopify_client = FakeShopifyClient()
    handle_delivery_note_submit(session, shopify_client, erpnext_client, dn)

    spy = MagicMock(wraps=erpnext_client)
    handle_shopify_fulfillment_webhook(session, spy, FULFILLMENT_PAYLOAD)

    spy.insert.assert_not_called()
    spy.submit.assert_not_called()
    assert erpnext_client.get_list("Delivery Note") == [erpnext_client.get_doc("Delivery Note", "DN-0001")]
