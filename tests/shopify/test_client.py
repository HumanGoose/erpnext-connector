import json

import httpx
import pytest

from connector.config import get_settings
from connector.shopify.client import ShopifyClient, ShopifyGraphQLError


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
