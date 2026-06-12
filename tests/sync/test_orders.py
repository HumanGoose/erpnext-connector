import copy
from unittest.mock import MagicMock

from sqlmodel import select

from connector.models import EntityType, RetryQueueEntry, RetryStatus, SyncDirection
from connector.sync import entities
from connector.sync.orders import (
    CANCELLED_FINGERPRINT,
    handle_erpnext_sales_order_cancel,
    handle_erpnext_sales_order_submit,
    handle_shopify_order_cancel,
    handle_shopify_order_create,
    handle_shopify_refund_create,
)
from tests.erpnext.fakes import FakeERPNextClient
from tests.shopify.fakes import FakeShopifyClient

VARIANT_GID = "gid://shopify/ProductVariant/10"
ITEM_CODE = "TEE-001"
ORDER_GID = "gid://shopify/Order/100"
CUSTOMER_GID = "gid://shopify/Customer/500"

ORDER_CREATE_PAYLOAD = {
    "id": 100,
    "admin_graphql_api_id": ORDER_GID,
    "total_price": "40.00",
    "customer": {
        "id": 500,
        "admin_graphql_api_id": CUSTOMER_GID,
        "first_name": "Jane",
        "last_name": "Doe",
        "email": "jane@example.com",
    },
    "line_items": [{"id": 1000, "variant_id": 10, "quantity": 2, "price": "20.00"}],
}


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


# --- Issue 17: Shopify Order -> ERPNext Sales Order + Sales Invoice + Payment Entry ---


def test_new_order_creates_sales_order_invoice_and_payment_entry(session):
    _seed_variant(session)
    client = FakeERPNextClient()

    handle_shopify_order_create(session, client, ORDER_CREATE_PAYLOAD)

    sales_orders = client.get_list("Sales Order")
    assert len(sales_orders) == 1
    so = sales_orders[0]
    assert so["items"] == [{"item_code": ITEM_CODE, "qty": 2, "rate": 20.0}]
    assert so["shopify_order_gid"] == ORDER_GID
    assert so["docstatus"] == 1

    invoices = client.get_list("Sales Invoice")
    assert len(invoices) == 1
    si = invoices[0]
    assert si["items"] == [{"item_code": ITEM_CODE, "qty": 2, "rate": 20.0}]
    assert si["grand_total"] == 40.0
    assert si["discount_amount"] == 0.0
    assert si["taxes"] == []
    assert si["docstatus"] == 1

    payments = client.get_list("Payment Entry")
    assert len(payments) == 1
    pe = payments[0]
    assert pe["payment_type"] == "Receive"
    assert pe["paid_amount"] == 40.0
    assert pe["references"] == [
        {"reference_doctype": "Sales Invoice", "reference_name": si["name"], "allocated_amount": 40.0}
    ]
    assert pe["docstatus"] == 1

    # Customer resolved/created inline (issue 15).
    customer_entity = entities.get_by_shopify_gid(session, EntityType.CUSTOMER, CUSTOMER_GID)
    assert customer_entity is not None
    assert so["customer"] == customer_entity.erpnext_name
    assert si["customer"] == customer_entity.erpnext_name
    assert pe["party"] == customer_entity.erpnext_name

    group = entities.get_group(session, ORDER_GID, EntityType.ORDER)
    assert len(group) == 3
    by_doctype = {e.erpnext_doctype: e for e in group}
    assert by_doctype["Sales Order"].shopify_gid == ORDER_GID
    assert by_doctype["Sales Order"].erpnext_name == so["name"]
    assert by_doctype["Sales Invoice"].shopify_gid is None
    assert by_doctype["Sales Invoice"].erpnext_name == si["name"]
    assert by_doctype["Payment Entry"].shopify_gid is None
    assert by_doctype["Payment Entry"].erpnext_name == pe["name"]
    for entity in group:
        assert entity.shopify_fingerprint == entity.erpnext_fingerprint


def test_redelivery_is_idempotent_no_duplicate_documents(session):
    _seed_variant(session)
    client = FakeERPNextClient()

    handle_shopify_order_create(session, client, ORDER_CREATE_PAYLOAD)

    spy = MagicMock(wraps=client)
    handle_shopify_order_create(session, spy, ORDER_CREATE_PAYLOAD)

    spy.insert.assert_not_called()
    spy.submit.assert_not_called()
    assert len(client.get_list("Sales Order")) == 1
    assert len(client.get_list("Sales Invoice")) == 1
    assert len(client.get_list("Payment Entry")) == 1


def test_order_with_no_customer_uses_guest(session):
    _seed_variant(session)
    client = FakeERPNextClient()
    payload = copy.deepcopy(ORDER_CREATE_PAYLOAD)
    del payload["customer"]

    handle_shopify_order_create(session, client, payload)

    so = client.get_list("Sales Order")[0]
    assert so["customer"] == "Guest"
    assert entities.get_by_shopify_gid(session, EntityType.CUSTOMER, CUSTOMER_GID) is None


# --- Issue 18: ERPNext Sales Order -> Shopify Order (orderCreate, idempotent, paid) ---


def _seed_sales_order(client: FakeERPNextClient) -> dict:
    so_doc = client.insert(
        {
            "doctype": "Sales Order",
            "name": "SO-0001",
            "customer": "Guest",
            "items": [{"item_code": ITEM_CODE, "qty": 2, "rate": 20.0}],
            "grand_total": 40.0,
        }
    )
    client.submit(so_doc)
    si_doc = client.insert(
        {
            "doctype": "Sales Invoice",
            "name": "SINV-0001",
            "customer": "Guest",
            "sales_order": "SO-0001",
            "items": [{"item_code": ITEM_CODE, "qty": 2, "rate": 20.0}],
            "grand_total": 40.0,
        }
    )
    client.submit(si_doc)
    return so_doc


def test_erpnext_sales_order_creates_shopify_order(session):
    erpnext_client = FakeERPNextClient()
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
    _seed_sales_order(erpnext_client)
    shopify_client = FakeShopifyClient()

    payload = erpnext_client.get_doc("Sales Order", "SO-0001")
    handle_erpnext_sales_order_submit(session, shopify_client, erpnext_client, payload)

    create_calls = [c for c in shopify_client.calls if c[0] == "create_order"]
    assert len(create_calls) == 1
    order_input = create_calls[0][1]["order_input"]
    assert order_input["lineItems"] == [
        {
            "variantId": VARIANT_GID,
            "quantity": 2,
            "priceSet": {"shopMoney": {"amount": "20.00", "currencyCode": "USD"}},
        }
    ]
    assert order_input["financialStatus"] == "PAID"
    assert order_input["transactions"][0]["amountSet"]["shopMoney"]["amount"] == "40.00"
    assert create_calls[0][1]["idempotency_key"] == "erpnext-sales-order-SO-0001"

    order_gid = next(iter(shopify_client.orders))
    assert erpnext_client.get_doc("Sales Order", "SO-0001")["shopify_order_gid"] == order_gid
    assert erpnext_client.get_doc("Sales Invoice", "SINV-0001")["shopify_order_gid"] == order_gid

    so_entity = entities.get_by_erpnext(session, EntityType.ORDER, "Sales Order", "SO-0001")
    assert so_entity.shopify_gid == order_gid
    assert so_entity.group_key == order_gid

    si_entity = entities.get_by_erpnext(session, EntityType.ORDER, "Sales Invoice", "SINV-0001")
    assert si_entity.shopify_gid is None
    assert si_entity.group_key == order_gid
    assert si_entity.shopify_fingerprint == so_entity.shopify_fingerprint


def test_erpnext_sales_order_skips_if_shopify_order_gid_already_set(session):
    erpnext_client = FakeERPNextClient()
    _seed_sales_order(erpnext_client)
    erpnext_client.set_value("Sales Order", "SO-0001", "shopify_order_gid", "gid://shopify/Order/999")
    shopify_client = FakeShopifyClient()
    spy = MagicMock(wraps=shopify_client)

    payload = erpnext_client.get_doc("Sales Order", "SO-0001")
    handle_erpnext_sales_order_submit(session, spy, erpnext_client, payload)

    spy.create_order.assert_not_called()
    assert entities.get_by_erpnext(session, EntityType.ORDER, "Sales Order", "SO-0001") is None


def test_redelivery_dedups_via_idempotency_key(session):
    erpnext_client = FakeERPNextClient()
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
    _seed_sales_order(erpnext_client)
    shopify_client = FakeShopifyClient()

    first_payload = erpnext_client.get_doc("Sales Order", "SO-0001")
    handle_erpnext_sales_order_submit(session, shopify_client, erpnext_client, first_payload)

    # Simulate a redelivered webhook carrying a pre-write snapshot (no shopify_order_gid yet).
    second_payload = copy.deepcopy(erpnext_client.get_doc("Sales Order", "SO-0001"))
    del second_payload["shopify_order_gid"]
    handle_erpnext_sales_order_submit(session, shopify_client, erpnext_client, second_payload)

    assert len(shopify_client.orders) == 1
    group = entities.get_group(session, next(iter(shopify_client.orders)), EntityType.ORDER)
    assert len(group) == 2


# --- Issue 21: Shopify Order cancellation -> ERPNext cascade ---


def _create_order_group(session):
    _seed_variant(session)
    client = FakeERPNextClient()
    handle_shopify_order_create(session, client, ORDER_CREATE_PAYLOAD)
    return client


CANCEL_PAYLOAD = {"id": 100, "admin_graphql_api_id": ORDER_GID}


def test_cancel_unpaid_order_cancels_so_si_pe(session):
    client = _create_order_group(session)

    handle_shopify_order_cancel(session, client, CANCEL_PAYLOAD)

    assert client.get_list("Sales Order")[0]["docstatus"] == 2
    assert client.get_list("Sales Invoice")[0]["docstatus"] == 2
    assert client.get_list("Payment Entry")[0]["docstatus"] == 2

    group = entities.get_group(session, ORDER_GID, EntityType.ORDER)
    assert len(group) == 3
    for entity in group:
        assert entity.shopify_fingerprint == CANCELLED_FINGERPRINT
        assert entity.erpnext_fingerprint == CANCELLED_FINGERPRINT


def test_cancel_paid_invoice_creates_credit_note(session):
    client = _create_order_group(session)
    si = client.get_list("Sales Invoice")[0]
    si_doc = client.get_doc("Sales Invoice", si["name"])
    si_doc["status"] = "Paid"

    handle_shopify_order_cancel(session, client, CANCEL_PAYLOAD)

    invoices = client.get_list("Sales Invoice")
    assert len(invoices) == 2  # original (untouched) + credit note
    credit = next(inv for inv in invoices if inv.get("is_return"))
    assert credit["return_against"] == si["name"]
    assert credit["items"] == [{"item_code": ITEM_CODE, "qty": -2, "rate": 20.0}]
    assert credit["docstatus"] == 1

    original = next(inv for inv in invoices if inv["name"] == si["name"])
    assert original["docstatus"] == 1  # Paid invoice left alone, not cancelled.

    assert client.get_list("Payment Entry")[0]["docstatus"] == 2
    assert client.get_list("Sales Order")[0]["docstatus"] == 2

    group = entities.get_group(session, ORDER_GID, EntityType.ORDER)
    for entity in group:
        assert entity.erpnext_fingerprint == CANCELLED_FINGERPRINT


def test_cancel_is_echo_safe_when_already_cancelled(session):
    client = _create_order_group(session)
    handle_shopify_order_cancel(session, client, CANCEL_PAYLOAD)

    spy = MagicMock(wraps=client)
    handle_shopify_order_cancel(session, spy, CANCEL_PAYLOAD)

    spy.get_doc.assert_not_called()
    spy.cancel.assert_not_called()
    spy.insert.assert_not_called()


# --- Issue 22: ERPNext Sales Order cancellation -> Shopify Order cancellation ---


def _create_pushed_order(session):
    erpnext_client = FakeERPNextClient()
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
    _seed_sales_order(erpnext_client)
    shopify_client = FakeShopifyClient()
    payload = erpnext_client.get_doc("Sales Order", "SO-0001")
    handle_erpnext_sales_order_submit(session, shopify_client, erpnext_client, payload)
    return erpnext_client, shopify_client


def test_erpnext_cancel_cancels_shopify_order(session):
    erpnext_client, shopify_client = _create_pushed_order(session)
    order_gid = next(iter(shopify_client.orders))

    handle_erpnext_sales_order_cancel(session, shopify_client, {"name": "SO-0001", "docstatus": 2})

    cancel_calls = [c for c in shopify_client.calls if c[0] == "cancel_order"]
    assert len(cancel_calls) == 1
    assert cancel_calls[0][1]["order_gid"] == order_gid
    assert shopify_client.orders[order_gid]["cancelled"] is True

    group = entities.get_group(session, order_gid, EntityType.ORDER)
    for entity in group:
        assert entity.shopify_fingerprint == CANCELLED_FINGERPRINT
        assert entity.erpnext_fingerprint == CANCELLED_FINGERPRINT


def test_erpnext_cancel_is_echo_safe_if_already_cancelled_via_shopify(session):
    erpnext_client, shopify_client = _create_pushed_order(session)
    so_entity = entities.get_by_erpnext(session, EntityType.ORDER, "Sales Order", "SO-0001")
    so_entity.erpnext_fingerprint = CANCELLED_FINGERPRINT
    entities.save(session, so_entity)

    spy = MagicMock(wraps=shopify_client)
    handle_erpnext_sales_order_cancel(session, spy, {"name": "SO-0001", "docstatus": 2})

    spy.cancel_order.assert_not_called()


def test_erpnext_cancel_non_cancellable_dead_letters(session):
    erpnext_client, shopify_client = _create_pushed_order(session)
    order_gid = next(iter(shopify_client.orders))
    shopify_client.non_cancellable.add(order_gid)
    so_entity = entities.get_by_erpnext(session, EntityType.ORDER, "Sales Order", "SO-0001")
    fp_before = so_entity.erpnext_fingerprint

    handle_erpnext_sales_order_cancel(session, shopify_client, {"name": "SO-0001", "docstatus": 2})

    retry_entries = session.exec(select(RetryQueueEntry)).all()
    assert len(retry_entries) == 1
    entry = retry_entries[0]
    assert entry.status == RetryStatus.DEAD_LETTER
    assert entry.direction == SyncDirection.ERPNEXT_TO_SHOPIFY
    assert entry.entity_type == EntityType.ORDER
    assert entry.payload == order_gid
    assert entry.synced_entity_id == so_entity.id
    assert entry.last_error

    session.refresh(so_entity)
    assert so_entity.erpnext_fingerprint == fp_before  # not marked cancelled


# --- Issue 23: Shopify refund -> ERPNext credit note / refund Payment Entry ---


REFUND_PAYLOAD = {
    "id": 1,
    "admin_graphql_api_id": "gid://shopify/Refund/1",
    "order_id": 100,
    "transactions": [{"amount": "20.00"}],
    "refund_line_items": [
        {"line_item": {"variant_id": 10, "price": "20.00"}, "quantity": 1, "subtotal": "20.00"}
    ],
}


def test_refund_creates_credit_note_and_refund_payment_entry(session):
    client = _create_order_group(session)
    original_si = client.get_list("Sales Invoice")[0]

    handle_shopify_refund_create(session, client, REFUND_PAYLOAD)

    invoices = client.get_list("Sales Invoice")
    assert len(invoices) == 2
    credit = next(inv for inv in invoices if inv.get("is_return"))
    assert credit["return_against"] == original_si["name"]
    assert credit["shopify_refund_gid"] == "gid://shopify/Refund/1"
    assert credit["shopify_order_gid"] == ORDER_GID
    assert credit["items"] == [{"item_code": ITEM_CODE, "qty": -1, "rate": 20.0}]
    assert credit["grand_total"] == -20.0
    assert credit["docstatus"] == 1

    refund_pes = client.get_list("Payment Entry", filters={"reference_no": "gid://shopify/Refund/1"})
    assert len(refund_pes) == 1
    refund_pe = refund_pes[0]
    assert refund_pe["payment_type"] == "Pay"
    assert refund_pe["paid_amount"] == 20.0
    assert refund_pe["references"] == [
        {"reference_doctype": "Sales Invoice", "reference_name": credit["name"], "allocated_amount": -20.0}
    ]
    assert refund_pe["docstatus"] == 1


def test_refund_redelivery_is_idempotent(session):
    client = _create_order_group(session)

    handle_shopify_refund_create(session, client, REFUND_PAYLOAD)
    handle_shopify_refund_create(session, client, REFUND_PAYLOAD)

    credits = client.get_list("Sales Invoice", filters={"shopify_refund_gid": "gid://shopify/Refund/1"})
    assert len(credits) == 1
    refund_pes = client.get_list("Payment Entry", filters={"reference_no": "gid://shopify/Refund/1"})
    assert len(refund_pes) == 1


VARIANT_GID_2 = "gid://shopify/ProductVariant/11"
ITEM_CODE_2 = "MUG-001"
ORDER_GID_2 = "gid://shopify/Order/200"

TWO_ITEM_ORDER_PAYLOAD = {
    "id": 200,
    "admin_graphql_api_id": ORDER_GID_2,
    "total_price": "50.00",
    "line_items": [
        {"id": 2000, "variant_id": 10, "quantity": 2, "price": "20.00"},
        {"id": 2001, "variant_id": 11, "quantity": 1, "price": "10.00"},
    ],
}

PARTIAL_REFUND_PAYLOAD = {
    "id": 2,
    "admin_graphql_api_id": "gid://shopify/Refund/2",
    "order_id": 200,
    "transactions": [{"amount": "10.00"}],
    "refund_line_items": [
        {"line_item": {"variant_id": 11, "price": "10.00"}, "quantity": 1, "subtotal": "10.00"}
    ],
}


def test_partial_refund_only_credits_refunded_line_item(session):
    _seed_variant(session)
    entities.save(
        session,
        None,
        entity_type=EntityType.VARIANT,
        shopify_gid=VARIANT_GID_2,
        group_key="gid://shopify/Product/2",
        erpnext_doctype="Item",
        erpnext_name=ITEM_CODE_2,
        shopify_fingerprint="seed",
        erpnext_fingerprint="seed",
    )
    client = FakeERPNextClient()
    handle_shopify_order_create(session, client, TWO_ITEM_ORDER_PAYLOAD)

    handle_shopify_refund_create(session, client, PARTIAL_REFUND_PAYLOAD)

    invoices = client.get_list("Sales Invoice")
    credit = next(inv for inv in invoices if inv.get("is_return"))
    assert credit["items"] == [{"item_code": ITEM_CODE_2, "qty": -1, "rate": 10.0}]
    assert credit["grand_total"] == -10.0
