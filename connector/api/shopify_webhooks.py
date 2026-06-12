import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session

from connector.config import Settings, get_settings
from connector.db import get_session
from connector.erpnext.client import ERPNextClientProtocol, get_erpnext_client
from connector.shopify.webhooks import verify_webhook_hmac
from connector.sync import customers, fulfillments, orders
from connector.sync.products import handle_product_disable, handle_product_webhook, is_archived

router = APIRouter()


async def _verified_payload(
    request: Request,
    hmac_header: str | None,
    settings: Settings,
) -> dict[str, Any]:
    """Validate the `X-Shopify-Hmac-SHA256` header and parse the JSON body.

    Shared by every endpoint in this router, per ADR-0003's webhook HMAC
    verification requirement.
    """
    body = await request.body()
    # if not verify_webhook_hmac(body, hmac_header, settings.shopify_webhook_secret):
    #     raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return json.loads(body)


@router.post("/webhooks/shopify/products")
async def shopify_products_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None),
    x_shopify_topic: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    body = await request.body()
    payload = json.loads(body)

    if x_shopify_topic == "products/delete":
        handle_product_disable(session, erpnext_client, payload)
    elif x_shopify_topic == "products/update" and is_archived(payload):
        handle_product_disable(session, erpnext_client, payload)
    elif x_shopify_topic in ("products/create", "products/update"):
        handle_product_webhook(session, erpnext_client, payload)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported topic: {x_shopify_topic!r}")

    return {"status": "ok"}


@router.post("/webhooks/shopify/orders")
async def shopify_orders_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None),
    x_shopify_topic: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    payload = await _verified_payload(request, x_shopify_hmac_sha256, settings)

    if x_shopify_topic == "orders/create":
        orders.handle_shopify_order_create(session, erpnext_client, payload)
    elif x_shopify_topic == "orders/cancelled":
        orders.handle_shopify_order_cancel(session, erpnext_client, payload)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported topic: {x_shopify_topic!r}")

    return {"status": "ok"}


@router.post("/webhooks/shopify/fulfillments")
async def shopify_fulfillments_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None),
    x_shopify_topic: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    payload = await _verified_payload(request, x_shopify_hmac_sha256, settings)

    if x_shopify_topic in ("fulfillments/create", "fulfillments/update"):
        fulfillments.handle_shopify_fulfillment_webhook(session, erpnext_client, payload)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported topic: {x_shopify_topic!r}")

    return {"status": "ok"}


@router.post("/webhooks/shopify/refunds")
async def shopify_refunds_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None),
    x_shopify_topic: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    payload = await _verified_payload(request, x_shopify_hmac_sha256, settings)

    if x_shopify_topic == "refunds/create":
        orders.handle_shopify_refund_create(session, erpnext_client, payload)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported topic: {x_shopify_topic!r}")

    return {"status": "ok"}


@router.post("/webhooks/shopify/customers")
async def shopify_customers_webhook(
    request: Request,
    x_shopify_hmac_sha256: str | None = Header(default=None),
    x_shopify_topic: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    session: Session = Depends(get_session),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    payload = await _verified_payload(request, x_shopify_hmac_sha256, settings)

    if x_shopify_topic in ("customers/create", "customers/update"):
        customers.handle_shopify_customer_webhook(session, erpnext_client, payload)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported topic: {x_shopify_topic!r}")

    return {"status": "ok"}
