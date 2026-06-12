from unittest.mock import MagicMock

from connector.sync.products import handle_product_disable, handle_product_webhook, is_archived
from tests.erpnext.fakes import FakeERPNextClient
from tests.sync.test_products import MULTI_VARIANT_PRODUCT, SIMPLE_PRODUCT


def _delete_payload(product_gid: str) -> dict:
    """A `products/delete` webhook payload: numeric `id` only, no `admin_graphql_api_id`."""
    numeric_id = product_gid.rsplit("/", 1)[-1]
    return {"id": int(numeric_id)}


def test_disable_simple_product(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, SIMPLE_PRODUCT)

    handle_product_disable(session, client, _delete_payload(SIMPLE_PRODUCT["admin_graphql_api_id"]))

    item = client.get_doc("Item", "TEE-001")
    assert item["disabled"] == 1


def test_disable_multi_variant_product_disables_template_and_variants(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, MULTI_VARIANT_PRODUCT)

    handle_product_disable(session, client, _delete_payload(MULTI_VARIANT_PRODUCT["admin_graphql_api_id"]))

    items = {item["item_code"]: item for item in client.get_list("Item")}
    assert items["snowboard"]["disabled"] == 1
    assert items["SB-S"]["disabled"] == 1
    assert items["SB-M"]["disabled"] == 1


def test_disable_is_idempotent_no_redundant_writes(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, MULTI_VARIANT_PRODUCT)
    handle_product_disable(session, client, _delete_payload(MULTI_VARIANT_PRODUCT["admin_graphql_api_id"]))

    spy = MagicMock(wraps=client)
    handle_product_disable(session, spy, _delete_payload(MULTI_VARIANT_PRODUCT["admin_graphql_api_id"]))

    spy.set_value.assert_not_called()


def test_disable_for_never_synced_product_is_noop(session):
    client = FakeERPNextClient()

    handle_product_disable(session, client, _delete_payload("gid://shopify/Product/999"))

    assert client.get_list("Item") == []


def test_archived_via_products_update_disables_item(session):
    client = FakeERPNextClient()
    handle_product_webhook(session, client, SIMPLE_PRODUCT)

    archived_payload = {**SIMPLE_PRODUCT, "status": "archived"}
    assert is_archived(archived_payload)

    handle_product_disable(session, client, archived_payload)

    item = client.get_doc("Item", "TEE-001")
    assert item["disabled"] == 1


def test_is_archived_handles_graphql_enum_casing():
    assert is_archived({"status": "ARCHIVED"}) is True
    assert is_archived({"status": "active"}) is False
    assert is_archived({}) is False
