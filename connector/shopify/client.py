import re
import time
from functools import lru_cache
from typing import Any, Protocol

import httpx

from connector.config import Settings, get_settings
from connector.shopify import mutations
from connector.shopify.models import GraphQLError, GraphQLResponse, ThrottleStatus


def _title_to_handle(title: str) -> str:
    """Approximate Shopify's handle generation from a product title.

    Shopify lowercases the title, replaces non-alphanumeric characters with
    hyphens, and collapses repeated hyphens. Used as a fallback when the
    product input didn't include an explicit `handle` field.
    """
    handle = title.lower()
    handle = re.sub(r"[^a-z0-9]+", "-", handle)
    return handle.strip("-")


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

    def find_product_by_handle(self, handle: str) -> dict[str, Any] | None: ...

    def create_product(self, product_input: dict[str, Any]) -> dict[str, Any]: ...

    def update_product(self, product_gid: str, product_input: dict[str, Any]) -> dict[str, Any]: ...

    def create_variants(self, product_gid: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def update_variants(self, product_gid: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]: ...

    def update_variant_price(self, product_gid: str, variant_gid: str, price: str) -> dict[str, Any]: ...

    def append_product_media(self, product_gid: str, media_urls: list[str]) -> dict[str, Any]: ...

    def get_or_create_product_image_id(self, product_gid: str, image_url: str) -> str | None: ...

    def set_inventory_quantity(self, inventory_item_gid: str, location_gid: str, quantity: int) -> dict[str, Any]: ...

    def create_customer(self, customer_input: dict[str, Any]) -> dict[str, Any]: ...

    def update_customer(self, customer_gid: str, customer_input: dict[str, Any]) -> dict[str, Any]: ...

    def create_order(self, order_input: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...

    def cancel_order(self, order_gid: str) -> dict[str, Any]: ...

    def create_fulfillment(self, fulfillment_input: dict[str, Any]) -> dict[str, Any]: ...

    def delete_product(self, product_gid: str) -> None: ...

    def delete_variants(self, product_gid: str, variant_gids: list[str]) -> None: ...


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
        timeout: float = 30.0,
    ) -> None:
        self._settings = settings
        self._cost_threshold = cost_threshold
        self._throttle_status: ThrottleStatus | None = None
        self._client = httpx.Client(transport=transport, timeout=timeout)

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

    def find_product_by_handle(self, handle: str) -> dict[str, Any] | None:
        """Query Shopify for a product by its handle. Returns the product dict
        (with variants list) or None if not found."""
        response = self.execute(mutations.PRODUCT_BY_HANDLE_QUERY, {"handle": f"handle:{handle}"})
        nodes = ((response.data or {}).get("products") or {}).get("nodes") or []
        if not nodes:
            return None
        product = nodes[0]
        variants = (product.get("variants") or {}).get("nodes") or []
        product["variants"] = variants
        return product

    def create_product(self, product_input: dict[str, Any]) -> dict[str, Any]:
        # `ProductInput` (API 2025-10) has no `variants` field; Shopify always
        # creates one default variant, which we then update in place via
        # `productVariantsBulkUpdate` to set its sku/price.
        variant_input = (product_input.pop("variants", None) or [None])[0]
        try:
            result = self._mutate(mutations.PRODUCT_CREATE, {"input": product_input}, "productCreate")
        except ShopifyUserError as exc:
            if any("handle" in (e.get("field") or "") or "Handle has already been taken" in (e.get("message") or "") for e in exc.user_errors):
                # A product with this handle already exists in Shopify (from a prior
                # incomplete sync or a manually created product). Find and return it
                # so the caller can link the ERPNext item to it instead of failing.
                handle = product_input.get("handle") or _title_to_handle(product_input.get("title") or "")
                existing = self.find_product_by_handle(handle)
                if existing:
                    return existing
            raise
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

    def update_variants(self, product_gid: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = self._mutate(
            mutations.PRODUCT_VARIANTS_BULK_UPDATE,
            {"productId": product_gid, "variants": variants},
            "productVariantsBulkUpdate",
        )
        return result.get("productVariants") or []

    def update_variant_price(self, product_gid: str, variant_gid: str, price: str) -> dict[str, Any]:
        variants = self.update_variants(product_gid, [{"id": variant_gid, "price": price}])
        return variants[0] if variants else {}

    def append_product_media(self, product_gid: str, media_urls: list[str]) -> dict[str, Any]:
        parsed = self.execute(mutations.PRODUCT_MEDIA_QUERY, {"id": product_gid})
        existing: set[str] = set()
        product_data = (parsed.data or {}).get("product") or {}
        for node in (product_data.get("media") or {}).get("nodes", []):
            url = (node.get("image") or {}).get("url")
            if url:
                existing.add(url.split("?")[0])  # strip query params for comparison

        new_media = [
            {"originalSource": url, "mediaContentType": "IMAGE"}
            for url in media_urls
            if url.split("?")[0] not in existing
        ]
        if not new_media:
            return {}
        return self._mutate(
            mutations.PRODUCT_CREATE_MEDIA, {"productId": product_gid, "media": new_media}, "productCreateMedia"
        )

    def get_or_create_product_image_id(self, product_gid: str, image_url: str) -> str | None:
        image_id = self._find_product_image_id(product_gid, image_url)
        if image_id:
            return image_id
        self.append_product_media(product_gid, [image_url])
        return self._find_product_image_id(product_gid, image_url)

    def _find_product_image_id(self, product_gid: str, image_url: str) -> str | None:
        response = self.execute(mutations.PRODUCT_IMAGES_QUERY, {"id": product_gid})
        product_data = (response.data or {}).get("product") or {}
        bare_url = image_url.split("?")[0]
        for node in (product_data.get("images") or {}).get("nodes") or []:
            if (node.get("src") or "").split("?")[0] == bare_url:
                return node["id"]
        return None

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

    def delete_product(self, product_gid: str) -> None:
        self._mutate(mutations.PRODUCT_DELETE, {"input": {"id": product_gid}}, "productDelete")

    def delete_variants(self, product_gid: str, variant_gids: list[str]) -> None:
        self._mutate(
            mutations.PRODUCT_VARIANTS_BULK_DELETE,
            {"productId": product_gid, "variantsIds": variant_gids},
            "productVariantsBulkDelete",
        )


@lru_cache
def get_shopify_client() -> ShopifyClientProtocol:
    """FastAPI dependency: a shared `ShopifyClient` instance.

    Tests override this dependency with a `FakeShopifyClient`.
    """
    return ShopifyClient(get_settings())
