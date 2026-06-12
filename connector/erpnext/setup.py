from connector.config import get_settings
from connector.erpnext.client import ERPNextClient, ERPNextClientProtocol

# Per PRD "ERPNext-side Custom Fields". `dt` is the Frappe DocType the field is added to.
CUSTOM_FIELDS: list[dict[str, str]] = [
    {
        "dt": "Item",
        "fieldname": "shopify_product_gid",
        "label": "Shopify Product GID",
        "fieldtype": "Data",
        "insert_after": "item_group",
    },
    {
        "dt": "Item",
        "fieldname": "shopify_variant_gid",
        "label": "Shopify Variant GID",
        "fieldtype": "Data",
        "insert_after": "shopify_product_gid",
    },
    {
        "dt": "Item",
        "fieldname": "shopify_inventory_item_gid",
        "label": "Shopify Inventory Item GID",
        "fieldtype": "Data",
        "insert_after": "shopify_variant_gid",
    },
    {
        "dt": "Item",
        "fieldname": "sync_to_shopify",
        "label": "Sync to Shopify",
        "fieldtype": "Check",
        "insert_after": "shopify_inventory_item_gid",
    },
    {
        "dt": "Customer",
        "fieldname": "shopify_customer_gid",
        "label": "Shopify Customer GID",
        "fieldtype": "Data",
        "insert_after": "customer_name",
    },
    {
        "dt": "Sales Order",
        "fieldname": "shopify_order_gid",
        "label": "Shopify Order GID",
        "fieldtype": "Data",
        "insert_after": "customer",
    },
    {
        "dt": "Sales Invoice",
        "fieldname": "shopify_order_gid",
        "label": "Shopify Order GID",
        "fieldtype": "Data",
        "insert_after": "customer",
    },
    {
        "dt": "Sales Invoice",
        "fieldname": "shopify_refund_gid",
        "label": "Shopify Refund GID",
        "fieldtype": "Data",
        "insert_after": "shopify_order_gid",
    },
    {
        "dt": "Delivery Note",
        "fieldname": "shopify_fulfillment_gid",
        "label": "Shopify Fulfillment GID",
        "fieldtype": "Data",
        "insert_after": "customer",
    },
]

# DocType -> (webhook-receiver path, docevents to subscribe).
WEBHOOK_DOCTYPES: dict[str, tuple[str, list[str]]] = {
    "Item": ("/webhooks/erpnext/items", ["after_insert", "on_update"]),
    "Item Price": ("/webhooks/erpnext/item-prices", ["after_insert", "on_update"]),
    "Customer": ("/webhooks/erpnext/customers", ["after_insert", "on_update"]),
    "Sales Order": ("/webhooks/erpnext/sales-orders", ["on_submit", "on_cancel"]),
    "Delivery Note": ("/webhooks/erpnext/delivery-notes", ["on_submit"]),
    "Stock Entry": ("/webhooks/erpnext/stock", ["on_submit"]),
    "Stock Reconciliation": ("/webhooks/erpnext/stock", ["on_submit"]),
}


def register_custom_fields(client: ERPNextClientProtocol) -> list[str]:
    """Create the Connector's required Custom Fields if they don't already exist.

    Returns the `dt.fieldname` identifiers of fields that were newly created.
    """
    created: list[str] = []
    for field in CUSTOM_FIELDS:
        existing = client.get_list(
            "Custom Field",
            filters={"dt": field["dt"], "fieldname": field["fieldname"]},
            fields=["name"],
        )
        if existing:
            continue
        client.insert({"doctype": "Custom Field", **field})
        created.append(f"{field['dt']}.{field['fieldname']}")
    return created


def register_webhooks(client: ERPNextClientProtocol, base_url: str) -> list[str]:
    """Create Frappe Webhook configs pointing at the Connector, idempotently.

    Returns the `DocType.docevent` identifiers of webhooks that were newly created.
    """
    base = base_url.rstrip("/")
    created: list[str] = []
    for doctype, (path, docevents) in WEBHOOK_DOCTYPES.items():
        request_url = f"{base}{path}"
        for docevent in docevents:
            existing = client.get_list(
                "Webhook",
                filters={
                    "webhook_doctype": doctype,
                    "webhook_docevent": docevent,
                    "request_url": request_url,
                },
                fields=["name"],
            )
            if existing:
                continue
            client.insert(
                {
                    "doctype": "Webhook",
                    # The Webhook DocType uses `autoname: prompt`, so a `name`
                    # must be supplied explicitly on insert.
                    "name": f"{doctype}-{docevent}",
                    "webhook_doctype": doctype,
                    "webhook_docevent": docevent,
                    "request_url": request_url,
                    "request_method": "POST",
                    "request_structure": "JSON",
                    # Sends the full document as JSON. `doc` in this context is
                    # already `doc.as_dict(convert_dates_to_str=True)` (see
                    # Frappe's `get_webhook_data`), so it's a plain dict with
                    # dates as strings - just serialize it directly. Uses
                    # Frappe's `json` filter (`frappe.as_json`), not Jinja's
                    # built-in `tojson`, for consistency with Frappe's own
                    # encoder.
                    "webhook_json": "{{ doc | json }}",
                    "enabled": 1,
                }
            )
            created.append(f"{doctype}.{docevent}")
    return created


def main() -> None:
    settings = get_settings()
    client = ERPNextClient(settings)

    created_fields = register_custom_fields(client)
    created_webhooks = register_webhooks(client, settings.connector_base_url)

    if created_fields:
        print(f"Created Custom Fields: {', '.join(created_fields)}")
    else:
        print("All Custom Fields already exist.")

    if created_webhooks:
        print(f"Created Webhooks: {', '.join(created_webhooks)}")
    else:
        print("All Webhooks already exist.")


if __name__ == "__main__":
    main()
