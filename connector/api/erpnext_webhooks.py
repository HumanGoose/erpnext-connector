import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from starlette.requests import ClientDisconnect
from sqlmodel import Session

from connector.db import get_session
from connector.erpnext.client import ERPNextClientProtocol, get_erpnext_client
from connector.shopify.client import ShopifyClientProtocol, get_shopify_client
from connector.sync import customers, fulfillments, inventory, orders, products_to_shopify

router = APIRouter()


async def _body(request: Request) -> dict[str, Any] | None:
    try:
        return json.loads(await request.body())
    except ClientDisconnect:
        return None


@router.post("/webhooks/erpnext/sales-orders")
async def erpnext_sales_orders_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Sales Order `on_submit`/`on_cancel` (issues 18, 22)."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    if payload.get("docstatus") == 2:
        background_tasks.add_task(orders.handle_erpnext_sales_order_cancel, session, shopify_client, payload)
    else:
        background_tasks.add_task(orders.handle_erpnext_sales_order_submit, session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/delivery-notes")
async def erpnext_delivery_notes_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Delivery Note `on_submit` (issue 19)."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    background_tasks.add_task(fulfillments.handle_delivery_note_submit, session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/items")
async def erpnext_items_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Item `after_insert`/`on_update` (issues 07, 09)."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    background_tasks.add_task(products_to_shopify.handle_item_webhook, session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/items/delete")
async def erpnext_items_delete_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
) -> dict[str, str]:
    """Frappe Server Script hook for Item `after_delete` — propagates deletion to Shopify."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    background_tasks.add_task(products_to_shopify.handle_item_delete_webhook, session, shopify_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/item-prices")
async def erpnext_item_prices_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Item Price `after_insert`/`on_update` (issue 11)."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    background_tasks.add_task(products_to_shopify.handle_item_price_webhook, session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/stock")
async def erpnext_stock_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Stock Entry / Stock Reconciliation `on_submit`."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    background_tasks.add_task(inventory.handle_stock_webhook, session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}


@router.post("/webhooks/erpnext/customers")
async def erpnext_customers_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    shopify_client: ShopifyClientProtocol = Depends(get_shopify_client),
    erpnext_client: ERPNextClientProtocol = Depends(get_erpnext_client),
) -> dict[str, str]:
    """Frappe Webhook for Customer `after_insert`/`on_update` (issue 16)."""
    payload = await _body(request)
    if payload is None:
        return {"status": "ok"}
    background_tasks.add_task(customers.handle_erpnext_customer_webhook, session, shopify_client, erpnext_client, payload)
    return {"status": "ok"}
