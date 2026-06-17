import json

import httpx
import pytest

from connector.config import get_settings
from connector.shopify.client import ShopifyClient, ShopifyGraphQLError, ShopifyUserError


def _throttled_response(currently_available: float, restore_rate: float = 50.0) -> dict:
    return {
        "data": {"shop": {"name": "test-shop"}},
        "extensions": {
            "cost": {
                "requestedQueryCost": 1,
                "actualQueryCost": 1,
                "throttleStatus": {
                    "maximumAvailable": 1000.0,
                    "currentlyAvailable": currently_available,
                    "restoreRate": restore_rate,
                },
            }
        },
    }


def test_paces_requests_based_on_throttle_status(monkeypatch):
    responses = iter([_throttled_response(currently_available=10), _throttled_response(currently_available=1000)])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    sleeps: list[float] = []
    monkeypatch.setattr("connector.shopify.client.time.sleep", lambda seconds: sleeps.append(seconds))

    client = ShopifyClient(settings=get_settings(), transport=httpx.MockTransport(handler))

    client.execute("query { shop { name } }")
    assert sleeps == []  # no throttle status yet on the first call

    client.execute("query { shop { name } }")
    assert sleeps == [pytest.approx((50.0 - 10.0) / 50.0)]


def test_execute_sends_access_token_header():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_throttled_response(currently_available=1000))

    settings = get_settings()
    client = ShopifyClient(settings=settings, transport=httpx.MockTransport(handler))

    client.execute("query { shop { name } }", {"foo": "bar"})

    assert captured["headers"]["X-Shopify-Access-Token"] == settings.shopify_access_token
    assert captured["body"]["variables"] == {"foo": "bar"}


def test_execute_raises_on_graphql_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": None,
                "errors": [{"message": "Field does not exist"}],
                "extensions": _throttled_response(currently_available=1000)["extensions"],
            },
        )

    client = ShopifyClient(settings=get_settings(), transport=httpx.MockTransport(handler))

    with pytest.raises(ShopifyGraphQLError):
        client.execute("query { invalid }")


def test_create_product_recovers_when_handle_already_taken():
    """When productCreate returns userErrors with 'Handle has already been taken',
    create_product must query for the existing product by handle and return it."""
    existing_product_gid = "gid://shopify/Product/9999"
    existing_variant_gid = "gid://shopify/ProductVariant/9999"
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        body = json.loads(request.content)
        query = body.get("query", "")
        ext = _throttled_response(currently_available=1000)["extensions"]

        if "productCreate" in query:
            return httpx.Response(200, json={
                "data": {"productCreate": {"product": None, "userErrors": [{"field": "handle", "message": "Handle has already been taken"}]}},
                "extensions": ext,
            })
        # products query by handle
        return httpx.Response(200, json={
            "data": {"products": {"nodes": [{"id": existing_product_gid, "handle": "my-widget", "variants": {"nodes": [{"id": existing_variant_gid, "sku": "W-1", "inventoryItem": {"id": "gid://shopify/InventoryItem/9999"}}]}}]}},
            "extensions": ext,
        })

    client = ShopifyClient(settings=get_settings(), transport=httpx.MockTransport(handler))
    result = client.create_product({"title": "My Widget"})

    assert result["id"] == existing_product_gid
    assert result["variants"][0]["id"] == existing_variant_gid
    assert call_count["n"] == 2  # one create attempt + one handle lookup
