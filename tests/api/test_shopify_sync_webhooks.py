import json

from fastapi.testclient import TestClient

from connector.main import app
from tests.api.test_shopify_webhooks import _sign

ORDER_PAYLOAD = {"id": 100, "admin_graphql_api_id": "gid://shopify/Order/100"}
FULFILLMENT_PAYLOAD = {"id": 1, "admin_graphql_api_id": "gid://shopify/Fulfillment/1", "order_id": 100}
REFUND_PAYLOAD = {"id": 1, "admin_graphql_api_id": "gid://shopify/Refund/1", "order_id": 100}
CUSTOMER_PAYLOAD = {"id": 500, "admin_graphql_api_id": "gid://shopify/Customer/500"}


def _post(client: TestClient, path: str, payload: dict, topic: str):
    body = json.dumps(payload).encode("utf-8")
    return client.post(
        path,
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": _sign(body),
            "X-Shopify-Topic": topic,
            "Content-Type": "application/json",
        },
    )


def test_orders_create_routes_to_order_create_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.orders.handle_shopify_order_create",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/orders", ORDER_PAYLOAD, "orders/create")

    assert response.status_code == 200
    assert calls == [ORDER_PAYLOAD]


def test_orders_cancelled_routes_to_order_cancel_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.orders.handle_shopify_order_cancel",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/orders", ORDER_PAYLOAD, "orders/cancelled")

    assert response.status_code == 200
    assert calls == [ORDER_PAYLOAD]


def test_orders_unsupported_topic_is_rejected(monkeypatch):
    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/orders", ORDER_PAYLOAD, "orders/fulfilled")

    assert response.status_code == 400


def test_orders_invalid_signature_is_rejected():
    body = json.dumps(ORDER_PAYLOAD).encode("utf-8")
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/orders",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": "not-a-valid-signature",
                "X-Shopify-Topic": "orders/create",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 401


def test_fulfillments_create_routes_to_fulfillment_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.fulfillments.handle_shopify_fulfillment_webhook",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/fulfillments", FULFILLMENT_PAYLOAD, "fulfillments/create")

    assert response.status_code == 200
    assert calls == [FULFILLMENT_PAYLOAD]


def test_fulfillments_update_routes_to_fulfillment_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.fulfillments.handle_shopify_fulfillment_webhook",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/fulfillments", FULFILLMENT_PAYLOAD, "fulfillments/update")

    assert response.status_code == 200
    assert calls == [FULFILLMENT_PAYLOAD]


def test_fulfillments_unsupported_topic_is_rejected():
    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/fulfillments", FULFILLMENT_PAYLOAD, "fulfillments/cancelled")

    assert response.status_code == 400


def test_refunds_create_routes_to_refund_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.orders.handle_shopify_refund_create",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/refunds", REFUND_PAYLOAD, "refunds/create")

    assert response.status_code == 200
    assert calls == [REFUND_PAYLOAD]


def test_refunds_unsupported_topic_is_rejected():
    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/refunds", REFUND_PAYLOAD, "refunds/update")

    assert response.status_code == 400


def test_customers_create_routes_to_customer_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.customers.handle_shopify_customer_webhook",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/customers", CUSTOMER_PAYLOAD, "customers/create")

    assert response.status_code == 200
    assert calls == [CUSTOMER_PAYLOAD]


def test_customers_update_routes_to_customer_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.sync.customers.handle_shopify_customer_webhook",
        lambda session, client, payload: calls.append(payload),
    )

    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/customers", CUSTOMER_PAYLOAD, "customers/update")

    assert response.status_code == 200
    assert calls == [CUSTOMER_PAYLOAD]


def test_customers_unsupported_topic_is_rejected():
    with TestClient(app) as client:
        response = _post(client, "/webhooks/shopify/customers", CUSTOMER_PAYLOAD, "customers/disable")

    assert response.status_code == 400
