import base64
import hashlib
import hmac

# Topic -> webhook-receiver path. Multiple topics intentionally share a path;
# the receiver routes on the `X-Shopify-Topic` header.
WEBHOOK_TOPICS: dict[str, str] = {
    "PRODUCTS_CREATE": "/webhooks/shopify/products",
    "PRODUCTS_UPDATE": "/webhooks/shopify/products",
    "PRODUCTS_DELETE": "/webhooks/shopify/products",
    "INVENTORY_LEVELS_UPDATE": "/webhooks/shopify/inventory",
    "ORDERS_CREATE": "/webhooks/shopify/orders",
    "ORDERS_CANCELLED": "/webhooks/shopify/orders",
    "FULFILLMENTS_CREATE": "/webhooks/shopify/fulfillments",
    "FULFILLMENTS_UPDATE": "/webhooks/shopify/fulfillments",
    "CUSTOMERS_CREATE": "/webhooks/shopify/customers",
    "CUSTOMERS_UPDATE": "/webhooks/shopify/customers",
    "REFUNDS_CREATE": "/webhooks/shopify/refunds",
}


def verify_webhook_hmac(body: bytes, hmac_header: str | None, secret: str) -> bool:
    """Validate the `X-Shopify-Hmac-SHA256` header against the configured webhook secret."""
    if not hmac_header:
        return False

    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, hmac_header)
