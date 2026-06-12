import json

import httpx

from connector.config import get_settings
from connector.shopify.client import ShopifyClient
from connector.shopify.setup import register_webhook_subscriptions
from connector.shopify.webhooks import WEBHOOK_TOPICS

EXTENSIONS = {
    "cost": {
        "requestedQueryCost": 1,
        "actualQueryCost": 1,
        "throttleStatus": {"maximumAvailable": 1000.0, "currentlyAvailable": 1000.0, "restoreRate": 50.0},
    }
}


def _make_handler(existing: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]

        if "webhookSubscriptionCreate" in query:
            topic = body["variables"]["topic"]
            callback_url = body["variables"]["webhookSubscription"]["callbackUrl"]
            new_id = f"gid://shopify/WebhookSubscription/{len(existing) + 1}"
            existing.append(
                {
                    "id": new_id,
                    "topic": topic,
                    "endpoint": {"__typename": "WebhookHttpEndpoint", "callbackUrl": callback_url},
                }
            )
            return httpx.Response(
                200,
                json={
                    "data": {
                        "webhookSubscriptionCreate": {
                            "webhookSubscription": {"id": new_id, "topic": topic},
                            "userErrors": [],
                        }
                    },
                    "extensions": EXTENSIONS,
                },
            )

        return httpx.Response(
            200,
            json={"data": {"webhookSubscriptions": {"nodes": existing}}, "extensions": EXTENSIONS},
        )

    return handler


def test_register_webhook_subscriptions_creates_missing_topics():
    base_url = "https://connector.example.com"
    existing = [
        {
            "id": "gid://shopify/WebhookSubscription/1",
            "topic": "PRODUCTS_CREATE",
            "endpoint": {
                "__typename": "WebhookHttpEndpoint",
                "callbackUrl": f"{base_url}{WEBHOOK_TOPICS['PRODUCTS_CREATE']}",
            },
        }
    ]

    client = ShopifyClient(settings=get_settings(), transport=httpx.MockTransport(_make_handler(existing)))

    created = register_webhook_subscriptions(client, base_url)

    assert "PRODUCTS_CREATE" not in created
    assert set(created) == set(WEBHOOK_TOPICS) - {"PRODUCTS_CREATE"}


def test_register_webhook_subscriptions_is_idempotent():
    base_url = "https://connector.example.com"
    existing = [
        {
            "id": "gid://shopify/WebhookSubscription/1",
            "topic": "PRODUCTS_CREATE",
            "endpoint": {
                "__typename": "WebhookHttpEndpoint",
                "callbackUrl": f"{base_url}{WEBHOOK_TOPICS['PRODUCTS_CREATE']}",
            },
        }
    ]

    client = ShopifyClient(settings=get_settings(), transport=httpx.MockTransport(_make_handler(existing)))

    first_pass = register_webhook_subscriptions(client, base_url)
    assert len(first_pass) == len(WEBHOOK_TOPICS) - 1
    assert len(existing) == len(WEBHOOK_TOPICS)

    second_pass = register_webhook_subscriptions(client, base_url)
    assert second_pass == []
