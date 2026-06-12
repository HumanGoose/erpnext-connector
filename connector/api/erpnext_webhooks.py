import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from connector.db import get_session
from connector.erpnext.client import ERPNextClientProtocol, get_erpnext_client
from connector.shopify.client import ShopifyClientProtocol, get_shopify_client
from connector.sync import customers, fulfillments, orders, products_to_shopify

router = APIRouter()


@router.post("/webhooks/erpnext/sales-orders")
async def erpnext_sales_orders_webhook(
    request: Request,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Sales Order `on_submit`/`on_cancel` (issues 18, 22).

    Both docevents are registered against this path (per `erpnext/setup.py`);
    the payload's `docstatus` (1 = submitted, 2 = cancelled) disambiguates,
    since the Frappe Webhook payload doesn't otherwise carry the docevent.
    """
    payload: dict[str, Any] = json.loads(await request.body())

    if payload.get("docstatus") == 2:
        orders.handle_erpnext_sales_order_cancel(session, shopify_client, payload)
    else:
        orders.handle_erpnext_sales_order_submit(session, shopify_client, erpnext_client, payload)

    return {"status": "ok"}


@router.post("/webhooks/erpnext/delivery-notes")
async def erpnext_delivery_notes_webhook(
    request: Request,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Delivery Note `on_submit` (issue 19)."""
    payload: dict[str, Any] = json.loads(await request.body())
    fulfillments.handle_delivery_note_submit(session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/items")
async def erpnext_items_webhook(
    request: Request,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Item `after_insert`/`on_update` (issues 07, 09)."""
    payload: dict[str, Any] = json.loads(await request.body())
    products_to_shopify.handle_item_webhook(session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/item-prices")
async def erpnext_item_prices_webhook(
    request: Request,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Item Price `after_insert`/`on_update` (issue 11)."""
    payload: dict[str, Any] = json.loads(await request.body())
    products_to_shopify.handle_item_price_webhook(session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/customers")
async def erpnext_customers_webhook(
    request: Request,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Customer `after_insert`/`on_update` (issue 16)."""
    payload: dict[str, Any] = json.loads(await request.body())
    customers.handle_erpnext_customer_webhook(session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}
