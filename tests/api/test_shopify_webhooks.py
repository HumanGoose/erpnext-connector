import base64
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from connector.config import get_settings
from connector.main import app

PRODUCT_PAYLOAD = {
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

BODY = json.dumps(PRODUCT_PAYLOAD).encode("utf-8")


def _sign(body: bytes) -> str:
    secret = get_settings().shopify_webhook_secret
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _fake_handler(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        "connector.api.shopify_webhooks.handle_product_webhook",
        lambda session, client, payload: calls.append(payload),
    )
    return calls


def test_products_create_routes_to_handler(monkeypatch):
    calls = _fake_handler(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=BODY,
            headers={
                "X-Shopify-Hmac-Sha256": _sign(BODY),
                "X-Shopify-Topic": "products/create",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert calls == [PRODUCT_PAYLOAD]


def test_products_update_routes_to_handler(monkeypatch):
    calls = _fake_handler(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=BODY,
            headers={
                "X-Shopify-Hmac-Sha256": _sign(BODY),
                "X-Shopify-Topic": "products/update",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert calls == [PRODUCT_PAYLOAD]


def test_invalid_signature_is_accepted_while_hmac_disabled(monkeypatch):
    """HMAC verification is currently commented out for development.
    When re-enabled, this should assert status_code == 401 and calls == []."""
    calls = _fake_handler(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=BODY,
            headers={
                "X-Shopify-Hmac-Sha256": "not-a-valid-signature",
                "X-Shopify-Topic": "products/create",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert calls == [PRODUCT_PAYLOAD]


def test_missing_signature_is_accepted_while_hmac_disabled(monkeypatch):
    """HMAC verification is currently commented out for development.
    When re-enabled, this should assert status_code == 401 and calls == []."""
    calls = _fake_handler(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=BODY,
            headers={
                "X-Shopify-Topic": "products/create",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert calls == [PRODUCT_PAYLOAD]


def test_products_delete_routes_to_disable_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "connector.api.shopify_webhooks.handle_product_disable",
        lambda session, client, payload: calls.append(payload),
    )
    delete_payload = {"id": 1}
    body = json.dumps(delete_payload).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": _sign(body),
                "X-Shopify-Topic": "products/delete",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert calls == [delete_payload]


def test_archived_products_update_routes_to_product_webhook(monkeypatch):
    """All products/update events (including archived) now go through
    handle_product_webhook, which applies status as a field update rather than
    a separate disable flow."""
    webhook_calls = []
    monkeypatch.setattr(
        "connector.api.shopify_webhooks.handle_product_webhook",
        lambda session, client, payload: webhook_calls.append(payload),
    )
    archived_payload = {**PRODUCT_PAYLOAD, "status": "archived"}
    body = json.dumps(archived_payload).encode("utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=body,
            headers={
                "X-Shopify-Hmac-Sha256": _sign(body),
                "X-Shopify-Topic": "products/update",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 200
    assert webhook_calls == [archived_payload]


def test_unsupported_topic_is_rejected(monkeypatch):
    calls = _fake_handler(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/shopify/products",
            content=BODY,
            headers={
                "X-Shopify-Hmac-Sha256": _sign(BODY),
                "X-Shopify-Topic": "products/whatever",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 400
    assert calls == []
