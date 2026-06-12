from connector.config import get_settings
from connector.shopify.client import ShopifyClient
from connector.shopify.models import WebhookSubscriptionNode
from connector.shopify.webhooks import WEBHOOK_TOPICS

WEBHOOK_SUBSCRIPTIONS_QUERY = """
query ConnectorWebhookSubscriptions($topics: [WebhookSubscriptionTopic!]) {
  webhookSubscriptions(first: 100, topics: $topics) {
    nodes {
      id
      topic
      endpoint {
        __typename
        ... on WebhookHttpEndpoint {
          callbackUrl
        }
      }
    }
  }
}
"""

WEBHOOK_SUBSCRIPTION_CREATE_MUTATION = """
mutation ConnectorWebhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
    webhookSubscription {
      id
      topic
    }
    userErrors {
      field
      message
    }
  }
}
"""


def list_webhook_subscriptions(client: ShopifyClient) -> list[WebhookSubscriptionNode]:
    response = client.execute(WEBHOOK_SUBSCRIPTIONS_QUERY, {"topics": list(WEBHOOK_TOPICS)})
    nodes = (response.data or {}).get("webhookSubscriptions", {}).get("nodes", [])
    return [WebhookSubscriptionNode.model_validate(node) for node in nodes]


def register_webhook_subscriptions(client: ShopifyClient, base_url: str) -> list[str]:
    """Register the Connector's required webhook subscriptions, idempotently.

    Returns the topics that were newly created (already-registered topic/URL
    pairs are left untouched).
    """
    existing = list_webhook_subscriptions(client)
    existing_pairs = {
        (node.topic, node.endpoint.callback_url)
        for node in existing
        if node.endpoint and node.endpoint.callback_url
    }

    base = base_url.rstrip("/")
    created: list[str] = []
    for topic, path in WEBHOOK_TOPICS.items():
        callback_url = f"{base}{path}"
        if (topic, callback_url) in existing_pairs:
            continue

        response = client.execute(
            WEBHOOK_SUBSCRIPTION_CREATE_MUTATION,
            {
                "topic": topic,
                "webhookSubscription": {"callbackUrl": callback_url, "format": "JSON"},
            },
        )
        payload = (response.data or {}).get("webhookSubscriptionCreate", {})
        user_errors = payload.get("userErrors") or []
        if user_errors:
            messages = "; ".join(error["message"] for error in user_errors)
            raise RuntimeError(f"webhookSubscriptionCreate failed for {topic}: {messages}")
        created.append(topic)

    return created


def main() -> None:
    settings = get_settings()
    with ShopifyClient(settings) as client:
        created = register_webhook_subscriptions(client, settings.connector_base_url)
    if created:
        print(f"Registered webhook subscriptions: {', '.join(created)}")
    else:
        print("All webhook subscriptions already registered.")


if __name__ == "__main__":
    main()
