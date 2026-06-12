import json

from fastapi.testclient import TestClient

from connector.main import app

SALES_ORDER_SUBMIT_PAYLOAD = {
    "doctype": "Sales Order",
    "name": "SO-0001",
    "docstatus": 1,
    "items": [{"item_code": "TEE-001", "qty": 2, "rate": 20.0}],
    "grand_total": 40.0,
}

SALES_ORDER_CANCEL_PAYLOAD = {"doctype": "Sales Order", "name": "SO-0001", "docstatus": 2}

DELIVERY_NOTE_PAYLOAD = {
    "doctype": "Delivery Note",
    "name": "DN-0001",
    "against_sales_order": "SO-0001",
    "items": [{"item_code": "TEE-001", "qty": 2, "against_sales_order": "SO-0001"}],
}

ITEM_PAYLOAD = {
    "doctype": "Item",
    "name": "snowboard",
    "item_code": "snowboard",
    "item_name": "Snowboard",
    "has_variants": 1,
    "sync_to_shopify": 1,
}

ITEM_PRICE_PAYLOAD = {
    "doctype": "Item Price",
    "item_code": "SB-S",
    "price_list": "Standard Selling",
    "price_list_rate": 120.0,
}

CUSTOMER_PAYLOAD = {
    "doctype": "Customer",
    "name": "CUST-0001",
    "customer_name": "Jane Doe",
    "email_id": "jane@example.com",
}


def _post(client: TestClient, path: str, payload: dict):
    return client.post(path, content=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})


def test_sales_order_submit_routes_to_submit_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.orders.handle_erpnext_sales_order_submit",
        lambda session, shopify_client, erpnext_client, payload: calls.append(payload),
    )
    monkeypatch.setattr(
        "connector.sync.orders.handle_erpnext_sales_order_cancel",
        lambda session, shopify_client, payload: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/erpnext/sales-orders", SALES_ORDER_SUBMIT_PAYLOAD)

    assert response.status_code == 200
    assert calls == [SALES_ORDER_SUBMIT_PAYLOAD]


def test_sales_order_cancel_routes_to_cancel_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.orders.handle_erpnext_sales_order_cancel",
        lambda session, shopify_client, payload: calls.append(payload),
    )
    monkeypatch.setattr(
        "connector.sync.orders.handle_erpnext_sales_order_submit",
        lambda session, shopify_client, erpnext_client, payload: (_ for _ in ()).throw(
            AssertionError("should not be called")
        ),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/erpnext/sales-orders", SALES_ORDER_CANCEL_PAYLOAD)

    assert response.status_code == 200
    assert calls == [SALES_ORDER_CANCEL_PAYLOAD]


def test_delivery_note_submit_routes_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.fulfillments.handle_delivery_note_submit",
        lambda session, shopify_client, erpnext_client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/erpnext/delivery-notes", DELIVERY_NOTE_PAYLOAD)

    assert response.status_code == 200
    assert calls == [DELIVERY_NOTE_PAYLOAD]


def test_item_webhook_routes_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.products_to_shopify.handle_item_webhook",
        lambda session, shopify_client, erpnext_client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/erpnext/items", ITEM_PAYLOAD)

    assert response.status_code == 200
    assert calls == [ITEM_PAYLOAD]


def test_item_price_webhook_routes_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.products_to_shopify.handle_item_price_webhook",
        lambda session, shopify_client, erpnext_client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/erpnext/item-prices", ITEM_PRICE_PAYLOAD)

    assert response.status_code == 200
    assert calls == [ITEM_PRICE_PAYLOAD]


def test_customer_webhook_routes_to_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.customers.handle_erpnext_customer_webhook",
        lambda session, shopify_client, erpnext_client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/erpnext/customers", CUSTOMER_PAYLOAD)

    assert response.status_code == 200
    assert calls == [CUSTOMER_PAYLOAD]
