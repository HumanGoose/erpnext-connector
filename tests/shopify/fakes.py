from collections import defaultdict
from typing import Any

from connector.shopify.client import ShopifyUserError


class FakeShopifyClient:
    """In-memory stand-in for `ShopifyClientProtocol`, for ERPNext->Shopify
    sync-handler tests. Records calls and assigns GIDs the way Shopify would,
    so tests can assert on the writes the Connector made."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.products: dict[str, dict[str, Any]] = {}
        self.variants: dict[str, dict[str, Any]] = {}
        self.customers: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.fulfillments: dict[str, dict[str, Any]] = {}
        self.inventory: dict[tuple[str, str], int] = {}
        self.media: dict[str, list[str]] = defaultdict(list)
        # orderCreate idempotency dedup, per ADR-0001 / story 27.
        self._orders_by_idempotency: dict[str, str] = {}
        # GIDs the test has marked non-cancellable (e.g. already fulfilled).
        self.non_cancellable: set[str] = set()
        self._counters: dict[str, int] = defaultdict(int)

    def _gid(self, resource: str) -> str:
        self._counters[resource] += 1
        return f"gid://shopify/{resource}/{self._counters[resource]}"

    def _record(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))

    def create_product(self, product_input: dict[str, Any]) -> dict[str, Any]:
        self._record("create_product", product_input=product_input)
        gid = self._gid("Product")
        variants = []
        for raw in product_input.get("variants") or [{}]:
            variant_gid = self._gid("ProductVariant")
            variant = {"id": variant_gid, "sku": raw.get("sku") or "", "price": raw.get("price")}
            self.variants[variant_gid] = variant
            variants.append({"id": variant_gid, "sku": variant["sku"]})
        self.products[gid] = {"id": gid, **product_input, "variants": variants}
        return {"id": gid, "variants": variants}

    def update_product(self, product_gid: str, product_input: dict[str, Any]) -> dict[str, Any]:
        self._record("update_product", product_gid=product_gid, product_input=product_input)
        self.products.setdefault(product_gid, {"id": product_gid}).update(product_input)
        return {"id": product_gid}

    def create_variants(self, product_gid: str, variants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self._record("create_variants", product_gid=product_gid, variants=variants)
        created = []
        for raw in variants:
            variant_gid = self._gid("ProductVariant")
            variant = {"id": variant_gid, "sku": raw.get("sku") or "", "price": raw.get("price")}
            self.variants[variant_gid] = variant
            created.append({"id": variant_gid, "sku": variant["sku"]})
        return created

    def update_variant_price(self, product_gid: str, variant_gid: str, price: str) -> dict[str, Any]:
        self._record("update_variant_price", product_gid=product_gid, variant_gid=variant_gid, price=price)
        self.variants.setdefault(variant_gid, {"id": variant_gid})["price"] = price
        return {"id": variant_gid, "price": price}

    def append_product_media(self, product_gid: str, media_urls: list[str]) -> dict[str, Any]:
        self._record("append_product_media", product_gid=product_gid, media_urls=media_urls)
        self.media[product_gid].extend(media_urls)
        return {"media": [{"id": self._gid("MediaImage")} for _ in media_urls]}

    def set_inventory_quantity(self, inventory_item_gid: str, location_gid: str, quantity: int) -> dict[str, Any]:
        self._record(
            "set_inventory_quantity",
            inventory_item_gid=inventory_item_gid,
            location_gid=location_gid,
            quantity=quantity,
        )
        self.inventory[(inventory_item_gid, location_gid)] = quantity
        return {"inventoryAdjustmentGroup": {"createdAt": "now"}}

    def create_customer(self, customer_input: dict[str, Any]) -> dict[str, Any]:
        self._record("create_customer", customer_input=customer_input)
        gid = self._gid("Customer")
        self.customers[gid] = {"id": gid, **customer_input}
        return {"id": gid}

    def update_customer(self, customer_gid: str, customer_input: dict[str, Any]) -> dict[str, Any]:
        self._record("update_customer", customer_gid=customer_gid, customer_input=customer_input)
        self.customers.setdefault(customer_gid, {"id": customer_gid}).update(customer_input)
        return {"id": customer_gid}

    def create_order(self, order_input: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        self._record("create_order", order_input=order_input, idempotency_key=idempotency_key)
        # Idempotency: a repeat key returns the original order, no new record.
        if idempotency_key in self._orders_by_idempotency:
            gid = self._orders_by_idempotency[idempotency_key]
            return {"id": gid}
        gid = self._gid("Order")
        self.orders[gid] = {"id": gid, **order_input}
        self._orders_by_idempotency[idempotency_key] = gid
        return {"id": gid}

    def cancel_order(self, order_gid: str) -> dict[str, Any]:
        self._record("cancel_order", order_gid=order_gid)
        if order_gid in self.non_cancellable:
            raise ShopifyUserError("orderCancel", [{"message": "Order cannot be cancelled (already fulfilled)"}])
        self.orders.setdefault(order_gid, {"id": order_gid})["cancelled"] = True
        return {"job": {"id": self._gid("Job")}}

    def create_fulfillment(self, fulfillment_input: dict[str, Any]) -> dict[str, Any]:
        self._record("create_fulfillment", fulfillment_input=fulfillment_input)
        gid = self._gid("Fulfillment")
        self.fulfillments[gid] = {"id": gid, **fulfillment_input}
        return {"id": gid, "status": "SUCCESS"}
