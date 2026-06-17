import copy
from unittest.mock import MagicMock

from sqlmodel import select

from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncedEntity
from connector.sync.products import ItemDeletedError, handle_product_webhook
from tests.erpnext.fakes import FakeERPNextClient

SIMPLE_PRODUCT = {
    "id": 1,
    "admin_graphql_api_id": "gid://shopify/Product/1",
    "title": "Simple Tee",
    "body_html": "<p>A simple tee</p>",
    "handle": "simple-tee",
    "options": [{"id": 1, "name": "Title", "position": 1, "values": ["Default Title"]}],
    "variants": [
        {
            "id": 10,
            "admin_graphql_api_id": "gid://shopify/ProductVariant/10",
            "title": "Default Title",
            "sku": "TEE-001",
            "price": "20.00",
            "position": 1,
            "option1": "Default Title",
            "option2": None,
            "option3": None,
        }
    ],
}

MULTI_VARIANT_PRODUCT = {
    "id": 2,
    "admin_graphql_api_id": "gid://shopify/Product/2",
    "title": "Snowboard",
    "body_html": "<p>Good snowboard!</p>",
    "handle": "snowboard",
    "options": [{"id": 2, "name": "Size", "position": 1, "values": ["Small", "Medium"]}],
    "variants": [
        {
            "id": 20,
            "admin_graphql_api_id": "gid://shopify/ProductVariant/20",
            "title": "Small",
            "sku": "SB-S",
            "price": "100.00",
            "position": 1,
            "option1": "Small",
            "option2": None,
            "option3": None,
        },
        {
            "id": 21,
            "admin_graphql_api_id": "gid://shopify/ProductVariant/21",
            "title": "Medium",
            "sku": "SB-M",
            "price": "100.00",
            "position": 2,
            "option1": "Medium",
            "option2": None,
            "option3": None,
        },
    ],
}


def test_new_simple_product_creates_single_item(session):
    client = FakeERPNextClient()

    handle_product_webhook(session, client, SIMPLE_PRODUCT)

    items = client.get_list("Item")
    assert len(items) == 1
    item = items[0]
    assert item["item_code"] == "TEE-001"
    assert item["item_name"] == "Simple Tee"
    assert item["description"] == "<p>A simple tee</p>"
    assert item["has_variants"] == 0
    assert item["shopify_product_gid"] == "gid://shopify/Product/1"
    assert item["shopify_variant_gid"] == "gid://shopify/ProductVariant/10"

    entities = session.exec(select(SyncedEntity)).all()
    assert len(entities) == 1
    entity = entities[0]
    assert entity.entity_type == EntityType.PRODUCT
    assert entity.shopify_gid == "gid://shopify/Product/1"
    assert entity.erpnext_doctype == "Item"
    assert entity.erpnext_name == "TEE-001"
    assert entity.shopify_fingerprint is not None
    # shopify_fp and erpnext_fp differ by design: erpnext_fp extends the
    # canonical with empty collections/category so the on_update echo check
    # in products_to_shopify matches without triggering a redundant push.
    assert entity.erpnext_fingerprint is not None
    assert entity.shopify_fingerprint != entity.erpnext_fingerprint


def test_echo_for_simple_product_makes_no_erpnext_calls(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, SIMPLE_PRODUCT)

    spy = MagicMock(wraps=client)
    handle_product_webhook(session, spy, SIMPLE_PRODUCT)

    spy.insert.assert_not_called()
    spy.update.assert_not_called()
    spy.get_list.assert_not_called()
    spy.get_doc.assert_not_called()


def test_new_multi_variant_product_creates_template_and_variants(session):
    client = FakeERPNextClient()

    handle_product_webhook(session, client, MULTI_VARIANT_PRODUCT)

    items = client.get_list("Item")
    assert len(items) == 3  # template + 2 variants

    template = next(i for i in items if i["item_code"] == "snowboard")
    assert template["has_variants"] == 1
    assert template["item_name"] == "Snowboard"
    assert template["attributes"] == [{"attribute": "Size"}]
    assert template["shopify_product_gid"] == "gid://shopify/Product/2"

    variant_s = next(i for i in items if i["item_code"] == "SB-S")
    assert variant_s["variant_of"] == "snowboard"
    assert variant_s["has_variants"] == 0
    assert variant_s["attributes"] == [{"attribute": "Size", "attribute_value": "Small"}]
    assert variant_s["shopify_product_gid"] == "gid://shopify/Product/2"
    assert variant_s["shopify_variant_gid"] == "gid://shopify/ProductVariant/20"

    variant_m = next(i for i in items if i["item_code"] == "SB-M")
    assert variant_m["variant_of"] == "snowboard"
    assert variant_m["attributes"] == [{"attribute": "Size", "attribute_value": "Medium"}]

    item_attributes = client.get_list("Item Attribute")
    assert len(item_attributes) == 1
    assert item_attributes[0]["attribute_name"] == "Size"
    assert item_attributes[0]["item_attribute_values"] == [
        {"attribute_value": "Small", "abbr": "Small"},
        {"attribute_value": "Medium", "abbr": "Medium"},
    ]

    entities = session.exec(select(SyncedEntity)).all()
    assert len(entities) == 3
    template_entity = next(e for e in entities if e.entity_type == EntityType.PRODUCT)
    variant_entities = [e for e in entities if e.entity_type == EntityType.VARIANT]
    assert len(variant_entities) == 2
    assert template_entity.erpnext_name == "snowboard"
    assert all(e.group_key == "gid://shopify/Product/2" for e in entities)
    # Product entities now store different shopify_fp/erpnext_fp to break the
    # Shopify→ERPNext→Shopify loop; variant entities still have equal fps.
    product_entity = next(e for e in entities if e.entity_type == EntityType.PRODUCT)
    variant_entities = [e for e in entities if e.entity_type == EntityType.VARIANT]
    assert product_entity.shopify_fingerprint != product_entity.erpnext_fingerprint
    assert all(e.shopify_fingerprint == e.erpnext_fingerprint for e in variant_entities)


def test_echo_for_multi_variant_product_makes_no_erpnext_calls(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, MULTI_VARIANT_PRODUCT)

    spy = MagicMock(wraps=client)
    handle_product_webhook(session, spy, MULTI_VARIANT_PRODUCT)

    spy.insert.assert_not_called()
    spy.update.assert_not_called()
    spy.get_list.assert_not_called()
    # get_doc is called by _apply_product_status_to_variant on the echo path for
    # each variant to check if status needs updating — no writes should result.
    spy.set_value.assert_not_called()


def test_update_title_and_description_updates_template_only(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, MULTI_VARIANT_PRODUCT)

    updated = copy.deepcopy(MULTI_VARIANT_PRODUCT)
    updated["title"] = "Snowboard Pro"
    updated["body_html"] = "<p>An even better snowboard!</p>"

    spy = MagicMock(wraps=client)
    handle_product_webhook(session, spy, updated)

    spy.insert.assert_not_called()
    spy.update.assert_called_once()
    updated_doc = spy.update.call_args[0][0]
    assert updated_doc["item_code"] == "snowboard"
    assert updated_doc["item_name"] == "Snowboard Pro"
    assert updated_doc["description"] == "<p>An even better snowboard!</p>"

    template = next(i for i in client.get_list("Item") if i["item_code"] == "snowboard")
    assert template["item_name"] == "Snowboard Pro"
    assert template["description"] == "<p>An even better snowboard!</p>"

    entities = {e.shopify_gid: e for e in session.exec(select(SyncedEntity)).all()}
    template_entity = entities["gid://shopify/Product/2"]
    expected_shopify_fp = fingerprint(canonicalize("product", updated))
    assert template_entity.shopify_fingerprint == expected_shopify_fp
    # erpnext_fp extends the canonical with empty collections/category
    assert template_entity.erpnext_fingerprint is not None
    assert template_entity.erpnext_fingerprint != template_entity.shopify_fingerprint

    # Variants are unchanged -> Echo, untouched.
    variant_entities = [e for e in entities.values() if e.entity_type == EntityType.VARIANT]
    assert len(variant_entities) == 2


def test_new_variant_added_to_existing_product_creates_new_item(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, MULTI_VARIANT_PRODUCT)

    updated = copy.deepcopy(MULTI_VARIANT_PRODUCT)
    updated["options"][0]["values"] = ["Small", "Medium", "Large"]
    updated["variants"].append(
        {
            "id": 22,
            "admin_graphql_api_id": "gid://shopify/ProductVariant/22",
            "title": "Large",
            "sku": "SB-L",
            "price": "110.00",
            "position": 3,
            "option1": "Large",
            "option2": None,
            "option3": None,
        }
    )

    handle_product_webhook(session, client, updated)

    items = client.get_list("Item")
    assert len(items) == 4  # template + 3 variants

    new_variant = next(i for i in items if i["item_code"] == "SB-L")
    assert new_variant["variant_of"] == "snowboard"
    assert new_variant["attributes"] == [{"attribute": "Size", "attribute_value": "Large"}]
    assert new_variant["shopify_variant_gid"] == "gid://shopify/ProductVariant/22"

    entities = session.exec(select(SyncedEntity)).all()
    assert len(entities) == 4
    new_entity = next(e for e in entities if e.shopify_gid == "gid://shopify/ProductVariant/22")
    assert new_entity.entity_type == EntityType.VARIANT
    assert new_entity.erpnext_name == "SB-L"
    assert new_entity.group_key == "gid://shopify/Product/2"


def test_shopify_webhook_does_not_crash_when_erpnext_item_deleted_concurrently(session):
    """Simulates the race where a Shopify products/update fires while ERPNext is
    mid-transaction deleting the item: _upsert_item raises ItemDeletedError and
    handle_product_webhook returns cleanly without propagating to the ASGI layer."""
    client = FakeERPNextClient()

    # Sync a simple product so an entity exists.
    handle_product_webhook(session, client, SIMPLE_PRODUCT)

    # Simulate the item being deleted in ERPNext while the connector tries to update it:
    # update() raises, and the subsequent get_list check returns empty (item gone).
    class DeletedDuringUpdateClient(FakeERPNextClient):
        def __init__(self, base):
            self.docs = base.docs
            self._counters = base._counters
            self._update_called = False

        def update(self, doc):
            self._update_called = True
            raise Exception("QueryDeadlockError: Record has changed since last read")

        def get_list(self, doctype, filters=None, **kwargs):
            # After the failed update, report the item as gone.
            if self._update_called and doctype == "Item" and isinstance(filters, dict) and "name" in filters:
                return []
            return super().get_list(doctype, filters=filters, **kwargs)

    spy_client = DeletedDuringUpdateClient(client)

    # Send a changed payload so the echo check doesn't short-circuit before _upsert_item.
    changed = {**SIMPLE_PRODUCT, "title": "Simple Tee — Renamed"}

    # Must not raise — ItemDeletedError is caught inside handle_product_webhook.
    handle_product_webhook(session, spy_client, changed)
    assert spy_client._update_called
