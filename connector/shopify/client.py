import time
from functools import lru_cache
from typing import Any, Protocol

import httpx

from connector.config import Settings, get_settings
from connector.shopify import mutations
from connector.shopify.models import GraphQLError, GraphQLResponse, ThrottleStatus


class ShopifyGraphQLError(Exception):
    def __init__(self, errors: list[GraphQLError]) -> None:
        self.errors = errors
        super().__init__("; ".join(error.message for error in errors))


class ShopifyUserError(Exception):
    """A Shopify mutation returned `userErrors` (a business-rule rejection,
    distinct from a transport/GraphQL error)."""

    def __init__(self, mutation: str, user_errors: list[dict[str, Any]]) -> None:
        self.user_errors = user_errors
        messages = "; ".join(error.get("message", "") for error in user_errors)
        super().__init__(f"{mutation} failed: {messages}")


class ShopifyClientProtocol(Protocol):
    """The semantic Shopify write surface the ERPNext->Shopify sync handlers
    depend on. Sync-handler tests fake this (per the PRD's Testing Decisions)
    rather than issuing real GraphQL."""

    def create_product(self, product_input: dict[str, Any]) -> dict[str, Any]: ...

    def update_product(self, product_gid: str, product_input: dict[str, Any]) -> dict[str, Any]: ...

    def create_variants(self, product_gid: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def update_variant_price(self, product_gid: str, variant_gid: str, price: str) -> dict[str, Any]: ...

    def append_product_media(self, product_gid: str, media_urls: list[str]) -> dict[str, Any]: ...

    def set_inventory_quantity(self, inventory_item_gid: str, location_gid: str, quantity: int) -> dict[str, Any]: ...

    def create_customer(self, customer_input: dict[str, Any]) -> dict[str, Any]: ...

    def update_customer(self, customer_gid: str, customer_input: dict[str, Any]) -> dict[str, Any]: ...

    def create_order(self, order_input: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

    def cancel_order(self, order_gid: str) -> dict[str, Any]: ...

    def create_fulfillment(self, fulfillment_input: dict[str, Any]) -> dict[str, Any]: ...


class ShopifyClient:
    """Wraps the Shopify GraphQL Admin API (per ADR-0001).

    Paces requests using `extensions.cost.throttleStatus` from each response
    rather than a per-second call-count bucket.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        cost_threshold: float = 50.0,
    ) -> None:
        self._settings = settings
        self._cost_threshold = cost_threshold
        self._throttle_status: ThrottleStatus | None = None
        self._client = httpx.Client(transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ShopifyClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        extensions: dict[str, Any] | None = None,
    ) -> GraphQLResponse:
        self._wait_for_capacity()

        body: dict[str, Any] = {"query": query, "variables": variables or {}}
        if extensions:
            body["extensions"] = extensions

        response = self._client.post(
            self._settings.shopify_graphql_url,
            json=body,
            headers={
                "X-Shopify-Access-Token": self._settings.shopify_access_token,
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()

        parsed = GraphQLResponse.model_validate(response.json())
        if parsed.extensions:
            self._throttle_status = parsed.extensions.cost.throttle_status
        if parsed.errors:
            raise ShopifyGraphQLError(parsed.errors)
        return parsed

    def _wait_for_capacity(self) -> None:
        status = self._throttle_status
        if status is None or status.currently_available >= self._cost_threshold:
            return

        deficit = self._cost_threshold - status.currently_available
        time.sleep(deficit / status.restore_rate)

    def _mutate(
        self,
        query: str,
        variables: dict[str, Any],
        root: str,
        *,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a mutation, raise on `userErrors`, and return its result object."""
        response = self.execute(query, variables, extensions=extensions)
        payload = (response.data or {}).get(root) or {}
        user_errors = payload.get("userErrors") or []
        if user_errors:
            raise ShopifyUserError(root, user_errors)
        return payload

    # --- semantic write methods (ShopifyClientProtocol) ---

    def create_product(self, product_input: dict[str, Any]) -> dict[str, Any]:
        # `ProductInput` (API 2025-10) has no `variants` field; Shopify always
        # creates one default variant, which we then update in place via
        # `productVariantsBulkUpdate` to set its sku/price.
        variant_input = (product_input.pop("variants", None) or [None])[0]
        result = self._mutate(mutations.PRODUCT_CREATE, {"input": product_input}, "productCreate")
        product = result.get("product") or {}
        variants = (product.get("variants") or {}).get("nodes") or []
        product["variants"] = variants

        if variant_input and variants:
            update: dict[str, Any] = {"id": variants[0]["id"]}
            if variant_input.get("price"):
                update["price"] = variant_input["price"]
            if variant_input.get("sku"):
                update["inventoryItem"] = {"sku": variant_input["sku"]}
            if len(update) > 1:
                updated = self._mutate(
                    mutations.PRODUCT_VARIANTS_BULK_UPDATE,
                    {"productId": product["id"], "variants": [update]},
                    "productVariantsBulkUpdate",
                )
                updated_variants = updated.get("productVariants") or []
                if updated_variants:
                    variants[0] = {**variants[0], **updated_variants[0]}

        return product

    def update_product(self, product_gid: str, product_input: dict[str, Any]) -> dict[str, Any]:
        result = self._mutate(
            mutations.PRODUCT_UPDATE, {"input": {"id": product_gid, **product_input}}, "productUpdate"
        )
        return result.get("product") or {}

    def create_variants(self, product_gid: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self._mutate(
            mutations.PRODUCT_VARIANTS_BULK_CREATE,
            {"productId": product_gid, "variants": variants},
            "productVariantsBulkCreate",
        )
        return result.get("productVariants") or []

    def update_variant_price(self, product_gid: str, variant_gid: str, price: str) -> dict[str, Any]:
        result = self._mutate(
            mutations.PRODUCT_VARIANTS_BULK_UPDATE,
            {"productId": product_gid, "variants": [{"id": variant_gid, "price": price}]},
            "productVariantsBulkUpdate",
        )
        variants = result.get("productVariants") or []
        return variants[0] if variants else {}

    def append_product_media(self, product_gid: str, media_urls: list[str]) -> dict[str, Any]:
        media = [
            {"originalSource": url, "mediaContentType": "IMAGE"} for url in media_urls
        ]
        return self._mutate(
            mutations.PRODUCT_CREATE_MEDIA, {"productId": product_gid, "media": media}, "productCreateMedia"
        )

    def set_inventory_quantity(self, inventory_item_gid: str, location_gid: str, quantity: int) -> dict[str, Any]:
        variables = {
            "input": {
                "name": "available",
                "reason": "correction",
                "ignoreCompareQuantity": True,
                "quantities": [
                    {
                        "inventoryItemId": inventory_item_gid,
                        "locationId": location_gid,
                        "quantity": quantity,
                    }
                ],
            }
        }
        return self._mutate(mutations.INVENTORY_SET_QUANTITIES, variables, "inventorySetQuantities")

    def create_customer(self, customer_input: dict[str, Any]) -> dict[str, Any]:
        result = self._mutate(mutations.CUSTOMER_CREATE, {"input": customer_input}, "customerCreate")
        return result.get("customer") or {}

    def update_customer(self, customer_gid: str, customer_input: dict[str, Any]) -> dict[str, Any]:
        result = self._mutate(
            mutations.CUSTOMER_UPDATE, {"input": {"id": customer_gid, **customer_input}}, "customerUpdate"
        )
        return result.get("customer") or {}

    def create_order(self, order_input: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        # The @idempotent directive (per ADR-0001) makes orderCreate safe to
        # retry: Shopify dedups on the key passed via extensions.
        result = self._mutate(
            mutations.ORDER_CREATE,
            {"order": order_input},
            "orderCreate",
            extensions={"idempotencyKey": idempotency_key},
        )
        return result.get("order") or {}

    def cancel_order(self, order_gid: str) -> dict[str, Any]:
        variables = {
            "orderId": order_gid,
            "reason": "OTHER",
            "refund": False,
            "restock": True,
            "notifyCustomer": True,
        }
        return self._mutate(mutations.ORDER_CANCEL, variables, "orderCancel")

    def create_fulfillment(self, fulfillment_input: dict[str, Any]) -> dict[str, Any]:
        result = self._mutate(
            mutations.FULFILLMENT_CREATE, {"fulfillment": fulfillment_input}, "fulfillmentCreateV2"
        )
        return result.get("fulfillment") or {}


@lru_cache
def get_shopify_client() -> ShopifyClientProtocol:
    """FastAPI dependency: a shared `ShopifyClient` instance.

    Tests override this dependency with a `FakeShopifyClient`.
    """
    return ShopifyClient(get_settings())
