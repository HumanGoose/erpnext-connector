"""Order lifecycle sync (issues 17, 18, 21, 22, 23).

An Order is a Synced Entity group: one Shopify Order paired with an ERPNext
document set (Sales Order + Sales Invoice + Payment Entry, plus later a Delivery
Note for fulfillment). All rows in the group share `group_key` = the Shopify
order GID. Shopify orders are pre-paid, so a new order creates and submits all
three ERPNext documents together.
"""

from typing import Any

from sqlmodel import Session

from connector import retry_queue
from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType, SyncDirection, SyncedEntity
from connector.shopify.client import ShopifyClientProtocol, ShopifyUserError
from connector.sync import customers, entities

# Sentinel canonical marking an Order's cancelled state, so a cancellation
# Echo (issue 21 <-> 22) is recognized without the order's line-item canonical
# changing.
CANCELLED_FINGERPRINT = fingerprint({"order_state": "cancelled"})


def _order_gid(payload: dict[str, Any]) -> str:
    gid = payload.get("admin_graphql_api_id")
    if gid:
        return str(gid)
    raw_id = payload.get("id")
    if raw_id is None:
        raise ValueError("Shopify order is missing 'id'")
    if isinstance(raw_id, str) and raw_id.startswith("gid://"):
        return raw_id
    return f"gid://shopify/Order/{raw_id}"


def _variant_gid(line: dict[str, Any]) -> str:
    if line.get("variant_gid"):
        return line["variant_gid"]
    variant = line.get("variant") or {}
    if variant.get("id"):
        return variant["id"]
    return f"gid://shopify/ProductVariant/{line.get('variant_id')}"


def _erpnext_line_items(session: Session, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Map a Shopify order's line items to ERPNext Items via variant Synced Entities."""
    items = []
    for line in payload.get("line_items") or []:
        variant_gid = _variant_gid(line)
        entity = entities.get_by_shopify_gid(session, EntityType.VARIANT, variant_gid)
        if entity is None:
            entity = entities.get_by_shopify_gid(session, EntityType.PRODUCT, variant_gid)
        if entity is None or entity.erpnext_name is None:
            raise ValueError(f"No Synced Entity for variant {variant_gid}")
        items.append(
            {
                "item_code": entity.erpnext_name,
                "qty": int(line.get("quantity") or 0),
                "rate": float(line.get("price") or 0),
                "variant_gid": variant_gid,
            }
        )
    return items


def _resolve_customer(session: Session, erpnext_client: ERPNextClientProtocol, payload: dict[str, Any]) -> str:
    """Return the ERPNext Customer name for the order, creating it inline (via
    issue 15's logic) if it hasn't synced yet."""
    customer = payload.get("customer") or {}
    if not customer:
        return "Guest"

    gid = customer.get("admin_graphql_api_id") or customer.get("id")
    if gid is not None and not str(gid).startswith("gid://"):
        gid = f"gid://shopify/Customer/{gid}"

    entity = entities.get_by_shopify_gid(session, EntityType.CUSTOMER, gid) if gid else None
    if entity is None:
        customers.handle_shopify_customer_webhook(session, erpnext_client, customer)
        entity = entities.get_by_shopify_gid(session, EntityType.CUSTOMER, gid)
    return entity.erpnext_name


# --- Issue 17: Shopify Order -> ERPNext Sales Order + Sales Invoice + Payment Entry ---


def handle_shopify_order_create(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    order_gid = _order_gid(payload)

    # Idempotency / webhook redelivery (story 27): one Shopify order never
    # produces more than one ERPNext document set.
    if entities.get_by_shopify_gid(session, EntityType.ORDER, order_gid) is not None:
        return

    canonical = canonicalize(EntityType.ORDER, payload)
    fp = fingerprint(canonical)
    customer_name = _resolve_customer(session, erpnext_client, payload)
    line_items = _erpnext_line_items(session, payload)
    item_rows = [{"item_code": i["item_code"], "qty": i["qty"], "rate": i["rate"]} for i in line_items]

    sales_order = _insert_submit(
        erpnext_client,
        {
            "doctype": "Sales Order",
            "customer": customer_name,
            "shopify_order_gid": order_gid,
            "items": item_rows,
        },
    )
    sales_invoice = _insert_submit(
        erpnext_client,
        {
            "doctype": "Sales Invoice",
            "customer": customer_name,
            "shopify_order_gid": order_gid,
            "items": item_rows,
            "taxes": _tax_rows(canonical),
            "discount_amount": float(canonical["discount"] or 0),
            "grand_total": float(canonical["total"] or 0),
        },
    )
    payment_entry = _insert_submit(
        erpnext_client,
        {
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "party_type": "Customer",
            "party": customer_name,
            "paid_amount": float(canonical["total"] or 0),
            "received_amount": float(canonical["total"] or 0),
            "reference_no": order_gid,
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": sales_invoice["name"],
                    "allocated_amount": float(canonical["total"] or 0),
                }
            ],
        },
    )

    _save_order_group(session, order_gid, fp, sales_order, sales_invoice, payment_entry, primary="Sales Order")


def _tax_rows(canonical: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    if canonical["tax"]:
        rows.append(
            {"charge_type": "Actual", "account_head": "Sales Tax", "description": "Tax", "tax_amount": float(canonical["tax"])}
        )
    if canonical["shipping"]:
        rows.append(
            {"charge_type": "Actual", "account_head": "Freight", "description": "Shipping", "tax_amount": float(canonical["shipping"])}
        )
    return rows


def _insert_submit(erpnext_client: ERPNextClientProtocol, doc: dict[str, Any]) -> dict[str, Any]:
    created = erpnext_client.insert(doc)
    erpnext_client.submit(created)
    return created


def _save_order_group(
    session: Session,
    order_gid: str,
    fp: str,
    sales_order: dict[str, Any],
    sales_invoice: dict[str, Any],
    payment_entry: dict[str, Any],
    *,
    primary: str,
) -> None:
    """Create one ORDER Synced Entity row per ERPNext document, sharing the
    order GID as group key. The row for `primary` carries `shopify_gid` so the
    order resolves from a Shopify-side webhook."""
    docs = [
        ("Sales Order", sales_order),
        ("Sales Invoice", sales_invoice),
        ("Payment Entry", payment_entry),
    ]
    for doctype, doc in docs:
        existing = entities.get_by_erpnext(session, EntityType.ORDER, doctype, doc["name"])
        entities.save(
            session,
            existing,
            entity_type=EntityType.ORDER,
            shopify_gid=order_gid if doctype == primary else None,
            group_key=order_gid,
            erpnext_doctype=doctype,
            erpnext_name=doc["name"],
            shopify_fingerprint=fp,
            erpnext_fingerprint=fp,
        )


# --- Issue 18: ERPNext Sales Order -> Shopify Order (orderCreate, idempotent, paid) ---


def handle_erpnext_sales_order_submit(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    # A Sales Order that already carries a Shopify GID originated from (or was
    # already pushed to) Shopify — nothing to do in this direction.
    if payload.get("shopify_order_gid"):
        return

    so_name = payload["name"]
    line_items = []
    for item in payload.get("items") or []:
        entity = entities.get_by_erpnext(session, EntityType.VARIANT, "Item", item["item_code"])
        if entity is None:
            entity = entities.get_by_erpnext(session, EntityType.PRODUCT, "Item", item["item_code"])
        if entity is None or entity.shopify_gid is None:
            raise ValueError(f"No Shopify variant Synced Entity for Item {item['item_code']}")
        line_items.append(
            {
                "variantId": entity.shopify_gid,
                "quantity": int(item.get("qty") or 0),
                "priceSet": {"shopMoney": {"amount": f"{float(item.get('rate') or 0):.2f}", "currencyCode": "USD"}},
            }
        )

    total = float(payload.get("grand_total") or payload.get("total") or 0)
    order_input = {
        "lineItems": line_items,
        "financialStatus": "PAID",
        # Mark already-paid so Shopify shows no outstanding balance (story 26).
        "transactions": [
            {
                "kind": "SALE",
                "status": "SUCCESS",
                "amountSet": {"shopMoney": {"amount": f"{total:.2f}", "currencyCode": "USD"}},
            }
        ],
    }
    # Stable idempotency key derived from the Sales Order (story 27): a retried
    # call with the same key cannot create a duplicate Shopify order.
    idempotency_key = f"erpnext-sales-order-{so_name}"
    order = shopify_client.create_order(order_input, idempotency_key)
    order_gid = order["id"]

    erpnext_client.set_value("Sales Order", so_name, "shopify_order_gid", order_gid)
    sales_invoice = _linked_sales_invoice(erpnext_client, so_name)
    if sales_invoice is not None:
        erpnext_client.set_value("Sales Invoice", sales_invoice["name"], "shopify_order_gid", order_gid)

    canonical_fp = fingerprint(canonicalize(EntityType.ORDER, _so_as_order(payload)))
    existing = entities.get_by_shopify_gid(session, EntityType.ORDER, order_gid)
    entities.save(
        session,
        existing,
        entity_type=EntityType.ORDER,
        shopify_gid=order_gid,
        group_key=order_gid,
        erpnext_doctype="Sales Order",
        erpnext_name=so_name,
        shopify_fingerprint=canonical_fp,
        erpnext_fingerprint=canonical_fp,
    )
    if sales_invoice is not None:
        si_existing = entities.get_by_erpnext(session, EntityType.ORDER, "Sales Invoice", sales_invoice["name"])
        entities.save(
            session,
            si_existing,
            entity_type=EntityType.ORDER,
            group_key=order_gid,
            erpnext_doctype="Sales Invoice",
            erpnext_name=sales_invoice["name"],
            shopify_fingerprint=canonical_fp,
            erpnext_fingerprint=canonical_fp,
        )


def _so_as_order(payload: dict[str, Any]) -> dict[str, Any]:
    """Shape an ERPNext Sales Order doc as an `order` canonical input."""
    return {
        "line_items": [
            {"variant_gid": "", "quantity": item.get("qty"), "price": item.get("rate")}
            for item in payload.get("items") or []
        ],
        "total_price": payload.get("grand_total") or payload.get("total"),
    }


def _linked_sales_invoice(erpnext_client: ERPNextClientProtocol, so_name: str) -> dict[str, Any] | None:
    matches = erpnext_client.get_list(
        "Sales Invoice", filters={"sales_order": so_name}, fields=["name"]
    )
    if matches:
        return erpnext_client.get_doc("Sales Invoice", matches[0]["name"])
    return None


# --- Issue 21: Shopify Order cancellation -> ERPNext cascade ---


def handle_shopify_order_cancel(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    order_gid = _order_gid(payload)
    group = entities.get_group(session, order_gid, EntityType.ORDER)
    if not group:
        return

    primary = next((e for e in group if e.shopify_gid == order_gid), group[0])
    if primary.erpnext_fingerprint == CANCELLED_FINGERPRINT:
        return  # Echo: already cancelled (e.g. our own cascade, or issue 22).

    by_doctype = {e.erpnext_doctype: e for e in group}
    _reverse_payment(erpnext_client, by_doctype.get("Payment Entry"))
    _cancel_or_credit_invoice(erpnext_client, by_doctype.get("Sales Invoice"))
    _cancel_sales_order(erpnext_client, by_doctype.get("Sales Order"))

    _mark_group_cancelled(session, group)


def _reverse_payment(erpnext_client: ERPNextClientProtocol, entity: SyncedEntity | None) -> None:
    if entity is None or entity.erpnext_name is None:
        return
    pe = erpnext_client.get_doc("Payment Entry", entity.erpnext_name)
    if pe.get("docstatus") == 1:
        erpnext_client.cancel("Payment Entry", entity.erpnext_name)


def _cancel_or_credit_invoice(erpnext_client: ERPNextClientProtocol, entity: SyncedEntity | None) -> None:
    if entity is None or entity.erpnext_name is None:
        return
    invoice = erpnext_client.get_doc("Sales Invoice", entity.erpnext_name)
    # A paid/reconciled invoice can't be cancelled outright -> issue a credit
    # note (return invoice) against it; otherwise cancel directly.
    if invoice.get("status") == "Paid":
        credit = erpnext_client.insert(
            {
                "doctype": "Sales Invoice",
                "is_return": 1,
                "return_against": entity.erpnext_name,
                "customer": invoice.get("customer"),
                "items": [
                    {"item_code": row["item_code"], "qty": -abs(row.get("qty") or 0), "rate": row.get("rate")}
                    for row in invoice.get("items") or []
                ],
            }
        )
        erpnext_client.submit(credit)
    elif invoice.get("docstatus") == 1:
        erpnext_client.cancel("Sales Invoice", entity.erpnext_name)


def _cancel_sales_order(erpnext_client: ERPNextClientProtocol, entity: SyncedEntity | None) -> None:
    if entity is None or entity.erpnext_name is None:
        return
    so = erpnext_client.get_doc("Sales Order", entity.erpnext_name)
    if so.get("docstatus") == 1:
        erpnext_client.cancel("Sales Order", entity.erpnext_name)


def _mark_group_cancelled(session: Session, group: list[SyncedEntity]) -> None:
    for entity in group:
        entity.shopify_fingerprint = CANCELLED_FINGERPRINT
        entity.erpnext_fingerprint = CANCELLED_FINGERPRINT
        entities.save(session, entity)


# --- Issue 22: ERPNext Sales Order cancellation -> Shopify Order cancellation ---


def handle_erpnext_sales_order_cancel(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    payload: dict[str, Any],
) -> None:
    so_name = payload["name"]
    entity = entities.get_by_erpnext(session, EntityType.ORDER, "Sales Order", so_name)
    if entity is None or entity.shopify_gid is None:
        return  # Not a Synced Order / never pushed to Shopify.

    if entity.erpnext_fingerprint == CANCELLED_FINGERPRINT:
        return  # Echo: cancellation originated from Shopify (issue 21).

    group = entities.get_group(session, entity.group_key or entity.shopify_gid, EntityType.ORDER)
    try:
        shopify_client.cancel_order(entity.shopify_gid)
    except ShopifyUserError as error:
        # Non-cancellable Shopify state (e.g. already fulfilled): record the
        # outcome in the retry queue's dead-letter lane rather than erroring or
        # retrying indefinitely (per issue 22's acceptance criteria).
        queued = retry_queue.enqueue(
            session,
            direction=SyncDirection.ERPNEXT_TO_SHOPIFY,
            entity_type=EntityType.ORDER,
            payload=entity.shopify_gid,
            synced_entity_id=entity.id,
        )
        retry_queue.record_failure(session, queued, str(error), max_attempts=1)
        return

    _mark_group_cancelled(session, group or [entity])


# --- Issue 23: Shopify refund -> ERPNext credit note / refund Payment Entry ---


def handle_shopify_refund_create(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    order_gid = _refund_order_gid(payload)
    group = entities.get_group(session, order_gid, EntityType.ORDER)
    if not group:
        return

    refund_gid = _refund_gid(payload)
    # Echo / redelivery dedup: a credit note already tagged with this refund.
    if erpnext_client.get_list(
        "Sales Invoice", filters={"shopify_refund_gid": refund_gid}, fields=["name"]
    ):
        return

    by_doctype = {e.erpnext_doctype: e for e in group}
    invoice_entity = by_doctype.get("Sales Invoice")
    if invoice_entity is None or invoice_entity.erpnext_name is None:
        return
    invoice = erpnext_client.get_doc("Sales Invoice", invoice_entity.erpnext_name)

    return_items = _refund_items(session, payload)
    refund_amount = _refund_amount(payload)

    credit = erpnext_client.insert(
        {
            "doctype": "Sales Invoice",
            "is_return": 1,
            "return_against": invoice_entity.erpnext_name,
            "customer": invoice.get("customer"),
            "shopify_refund_gid": refund_gid,
            "shopify_order_gid": order_gid,
            "items": return_items,
            "grand_total": -abs(refund_amount),
        }
    )
    erpnext_client.submit(credit)

    refund_pe = erpnext_client.insert(
        {
            "doctype": "Payment Entry",
            "payment_type": "Pay",
            "party_type": "Customer",
            "party": invoice.get("customer"),
            "paid_amount": refund_amount,
            "received_amount": refund_amount,
            "reference_no": refund_gid,
            "references": [
                {
                    "reference_doctype": "Sales Invoice",
                    "reference_name": credit["name"],
                    "allocated_amount": -abs(refund_amount),
                }
            ],
        }
    )
    erpnext_client.submit(refund_pe)


def _refund_order_gid(payload: dict[str, Any]) -> str:
    order_id = payload.get("order_id")
    if order_id is None:
        return _order_gid(payload.get("order") or {})
    if isinstance(order_id, str) and order_id.startswith("gid://"):
        return order_id
    return f"gid://shopify/Order/{order_id}"


def _refund_gid(payload: dict[str, Any]) -> str:
    gid = payload.get("admin_graphql_api_id") or payload.get("id")
    if isinstance(gid, str) and gid.startswith("gid://"):
        return gid
    return f"gid://shopify/Refund/{gid}"


def _refund_items(session: Session, payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for refund_line in payload.get("refund_line_items") or []:
        line = refund_line.get("line_item") or refund_line
        variant_gid = _variant_gid(line)
        entity = entities.get_by_shopify_gid(session, EntityType.VARIANT, variant_gid)
        if entity is None:
            entity = entities.get_by_shopify_gid(session, EntityType.PRODUCT, variant_gid)
        if entity is None or entity.erpnext_name is None:
            continue
        qty = int(refund_line.get("quantity") or line.get("quantity") or 0)
        items.append(
            {
                "item_code": entity.erpnext_name,
                "qty": -abs(qty),
                "rate": float(line.get("price") or 0),
            }
        )
    return items


def _refund_amount(payload: dict[str, Any]) -> float:
    total = 0.0
    for txn in payload.get("transactions") or []:
        total += float(txn.get("amount") or 0)
    if total:
        return total
    # Fall back to summing refunded line subtotals.
    for refund_line in payload.get("refund_line_items") or []:
        total += float(refund_line.get("subtotal") or 0)
    return total
