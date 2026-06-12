import copy
from unittest.mock import MagicMock

from sqlmodel import select

from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncedEntity
from connector.sync import entities
from connector.sync.customers import handle_erpnext_customer_webhook, handle_shopify_customer_webhook
from tests.erpnext.fakes import FakeERPNextClient
from tests.shopify.fakes import FakeShopifyClient

SHOPIFY_CUSTOMER = {
    "id": 1,
    "admin_graphql_api_id": "gid://shopify/Customer/1",
    "email": "jane@example.com",
    "first_name": "Jane",
    "last_name": "Doe",
    "phone": "+15551234567",
    "addresses": [
        {
            "address1": "123 Main St",
            "address2": "",
            "city": "Springfield",
            "province": "IL",
            "country": "United States",
            "zip": "62704",
        }
    ],
}


def test_new_customer_creates_erpnext_customer_with_denormalized_fields(session):
    client = FakeERPNextClient()

    handle_shopify_customer_webhook(session, client, SHOPIFY_CUSTOMER)

    customers = client.get_list("Customer")
    assert len(customers) == 1
    customer = customers[0]
    assert customer["customer_name"] == "Jane Doe"
    assert customer["customer_type"] == "Individual"
    assert customer["email_id"] == "jane@example.com"
    assert customer["mobile_no"] == "+15551234567"
    assert customer["addresses"] == [
        {
            "address1": "123 Main St",
            "address2": "",
            "city": "Springfield",
            "province": "IL",
            "country": "United States",
            "zip": "62704",
        }
    ]
    assert customer["shopify_customer_gid"] == "gid://shopify/Customer/1"

    rows = session.exec(select(SyncedEntity)).all()
    assert len(rows) == 1
    entity = rows[0]
    assert entity.entity_type == EntityType.CUSTOMER
    assert entity.shopify_gid == "gid://shopify/Customer/1"
    assert entity.group_key == "gid://shopify/Customer/1"
    assert entity.erpnext_doctype == "Customer"
    assert entity.erpnext_name == customer["name"]
    assert entity.shopify_fingerprint is not None
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_echo_for_existing_customer_makes_no_erpnext_calls(session):
    client = FakeERPNextClient()
    handle_shopify_customer_webhook(session, client, SHOPIFY_CUSTOMER)

    spy = MagicMock(wraps=client)
    handle_shopify_customer_webhook(session, spy, SHOPIFY_CUSTOMER)

    spy.insert.assert_not_called()
    spy.update.assert_not_called()


def test_update_existing_customer_updates_erpnext_customer_and_refreshes_fingerprints(session):
    client = FakeERPNextClient()
    handle_shopify_customer_webhook(session, client, SHOPIFY_CUSTOMER)
    original_name = session.exec(select(SyncedEntity)).one().erpnext_name

    updated = copy.deepcopy(SHOPIFY_CUSTOMER)
    updated["phone"] = "+15559876543"
    updated["email"] = "jane.doe@example.com"

    spy = MagicMock(wraps=client)
    handle_shopify_customer_webhook(session, spy, updated)

    spy.insert.assert_not_called()
    spy.update.assert_called_once()
    updated_doc = spy.update.call_args[0][0]
    assert updated_doc["name"] == original_name
    assert updated_doc["email_id"] == "jane.doe@example.com"
    assert updated_doc["mobile_no"] == "+15559876543"

    customer = client.get_doc("Customer", original_name)
    assert customer["email_id"] == "jane.doe@example.com"
    assert customer["mobile_no"] == "+15559876543"

    entity = session.exec(select(SyncedEntity)).one()
    expected_fp = fingerprint(canonicalize(EntityType.CUSTOMER, updated))
    assert entity.shopify_fingerprint == expected_fp
    assert entity.erpnext_fingerprint == expected_fp
    assert entity.erpnext_name == original_name


ERPNEXT_CUSTOMER = {
    "doctype": "Customer",
    "name": "CUST-0001",
    "customer_name": "Jane Doe",
    "customer_type": "Individual",
    "email_id": "jane@example.com",
    "mobile_no": "+15551234567",
    "addresses": [
        {
            "address1": "123 Main St",
            "address2": "",
            "city": "Springfield",
            "province": "IL",
            "country": "United States",
            "zip": "62704",
        }
    ],
}


def test_new_erpnext_customer_creates_shopify_customer(session):
    erpnext_client = FakeERPNextClient()
    shopify_client = FakeShopifyClient()
    customer = erpnext_client.insert(dict(ERPNEXT_CUSTOMER))

    handle_erpnext_customer_webhook(session, shopify_client, erpnext_client, customer)

    assert len(shopify_client.calls) == 1
    method, kwargs = shopify_client.calls[0]
    assert method == "create_customer"
    customer_input = kwargs["customer_input"]
    assert customer_input["firstName"] == "Jane"
    assert customer_input["lastName"] == "Doe"
    assert customer_input["email"] == "jane@example.com"
    assert customer_input["phone"] == "+15551234567"
    assert customer_input["addresses"][0]["city"] == "Springfield"

    gid = erpnext_client.get_doc("Customer", "CUST-0001")["shopify_customer_gid"]
    assert gid

    rows = session.exec(select(SyncedEntity)).all()
    assert len(rows) == 1
    entity = rows[0]
    assert entity.entity_type == EntityType.CUSTOMER
    assert entity.shopify_gid == gid
    assert entity.group_key == gid
    assert entity.erpnext_doctype == "Customer"
    assert entity.erpnext_name == "CUST-0001"
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_echo_for_existing_erpnext_customer_makes_no_shopify_calls(session):
    erpnext_client = FakeERPNextClient()
    shopify_client = FakeShopifyClient()
    customer = erpnext_client.insert(dict(ERPNEXT_CUSTOMER))

    handle_erpnext_customer_webhook(session, shopify_client, erpnext_client, customer)

    spy = MagicMock(wraps=shopify_client)
    handle_erpnext_customer_webhook(session, spy, erpnext_client, customer)

    spy.create_customer.assert_not_called()
    spy.update_customer.assert_not_called()


def test_update_existing_erpnext_customer_updates_shopify_customer(session):
    erpnext_client = FakeERPNextClient()
    shopify_client = FakeShopifyClient()
    customer = erpnext_client.insert(dict(ERPNEXT_CUSTOMER))

    handle_erpnext_customer_webhook(session, shopify_client, erpnext_client, customer)
    gid = erpnext_client.get_doc("Customer", "CUST-0001")["shopify_customer_gid"]

    updated = dict(customer)
    updated["email_id"] = "jane.doe@newmail.com"
    updated["mobile_no"] = "+15559999999"

    spy = MagicMock(wraps=shopify_client)
    handle_erpnext_customer_webhook(session, spy, erpnext_client, updated)

    spy.create_customer.assert_not_called()
    spy.update_customer.assert_called_once()
    args, _ = spy.update_customer.call_args
    assert args[0] == gid
    assert args[1]["email"] == "jane.doe@newmail.com"
    assert args[1]["phone"] == "+15559999999"

    entity = entities.get_by_erpnext(session, EntityType.CUSTOMER, "Customer", "CUST-0001")
    assert entity.shopify_fingerprint == entity.erpnext_fingerprint
