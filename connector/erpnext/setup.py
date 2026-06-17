from typing import Any

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
        "fieldname": "shopify_vendor",
        "label": "Shopify Vendor",
        "fieldtype": "Data",
        "insert_after": "shopify_inventory_item_gid",
    },
    {
        "dt": "Item",
        "fieldname": "shopify_tags",
        "label": "Shopify Tags",
        "fieldtype": "Small Text",
        "insert_after": "shopify_vendor",
    },
    {
        "dt": "Item",
        "fieldname": "sync_to_shopify",
        "label": "Sync to Shopify",
        "fieldtype": "Check",
        "insert_after": "shopify_tags",
    },
    {
        "dt": "Item",
        "fieldname": "shopify_status",
        "label": "Shopify Status",
        "fieldtype": "Select",
        "options": "Active\nDraft\nArchived\nUnlisted",
        "default": "Active",
        "insert_after": "sync_to_shopify",
        "read_only_depends_on": "eval:doc.variant_of",
    },
    {
        "dt": "Item",
        "fieldname": "shopify_collections",
        "label": "Shopify Collections",
        "fieldtype": "Small Text",
        "insert_after": "shopify_status",
        "read_only_depends_on": "eval:doc.variant_of",
    },
    {
        "dt": "Item",
        "fieldname": "shopify_category_gid",
        "label": "Shopify Category GID",
        "fieldtype": "Data",
        "insert_after": "shopify_collections",
        "read_only_depends_on": "eval:doc.variant_of",
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
# List of (doctype, connector-path, frappe-docevents) tuples.
# Multiple rows with the same doctype are fine — each (doctype, docevent) pair
# becomes its own Frappe Webhook record named "{doctype}-{docevent}".
WEBHOOK_REGISTRATIONS: list[tuple[str, str, list[str]]] = [
    ("Item", "/webhooks/erpnext/items", ["after_insert", "on_update"]),
    # before_delete fires while the doc still exists in the DB, so the payload
    # includes shopify_product_gid. Frappe Webhooks are reliable; Server Scripts
    # are sandboxed and have been the source of silent failures.
    ("Item", "/webhooks/erpnext/items/delete", ["on_trash"]),
    ("Item Price", "/webhooks/erpnext/item-prices", ["after_insert", "on_update"]),
    ("Customer", "/webhooks/erpnext/customers", ["after_insert", "on_update"]),
    ("Sales Order", "/webhooks/erpnext/sales-orders", ["on_submit", "on_cancel"]),
    ("Delivery Note", "/webhooks/erpnext/delivery-notes", ["on_submit"]),
    ("Stock Entry", "/webhooks/erpnext/stock", ["on_submit"]),
    ("Stock Reconciliation", "/webhooks/erpnext/stock", ["on_submit"]),
]


_ITEM_FORM_CLIENT_SCRIPT = """\
frappe.ui.form.on("Item", {
    refresh: function(frm) {
        // ── Description ─────────────────────────────────────────────────
        // section_break_11 is ERPNext's built-in "Description" section on
        // Item, which is collapsible by default. Expand it automatically so
        // the description field is always visible without an extra click.
        var desc_section = frm.get_field("section_break_11");
        if (desc_section && desc_section.collapse) {
            desc_section.collapse(false);
        }

        // ── Image ────────────────────────────────────────────────────────
        // The standard `image` field (Attach Image) sits above the column
        // break at the top-left, but shows as a small grey stub when empty.
        // Give it enough height and a visible border so it reads as a clear
        // upload target.
        connector_style_image_field(frm);
    },

    image: function(frm) {
        // Re-apply styling after the image is attached/removed so the
        // preview thumbnail is also sized consistently.
        connector_style_image_field(frm);
    }
});

function connector_style_image_field(frm) {
    var field = frm.fields_dict["image"];
    if (!field || !field.$wrapper) return;
    var $w = field.$wrapper;

    // Minimum height so the upload area is clearly clickable when empty.
    $w.find(".control-input").css("min-height", "120px");

    // Preview: constrain and centre the thumbnail.
    $w.find("img").css({
        "display": "block",
        "max-height": "160px",
        "max-width": "100%",
        "object-fit": "contain",
        "margin": "4px auto",
        "border-radius": "4px"
    });
}
"""

_ITEM_DELETE_SCRIPT = """\
import json

url = "{base_url}webhooks/erpnext/items/delete"
data = json.dumps({{
    "name": doc.name,
    "doctype": doc.doctype,
    "shopify_product_gid": doc.get("shopify_product_gid") or "",
    "shopify_variant_gid": doc.get("shopify_variant_gid") or "",
    "variant_of": doc.get("variant_of") or "",
}})
try:
    session = frappe.utils.get_request_session()
    session.post(url, data=data, headers={{"Content-Type": "application/json"}}, timeout=5)
except Exception as e:
    frappe.log_error(message=str(e), title="Connector Item Delete")
"""


def register_custom_fields(client: ERPNextClientProtocol) -> list[str]:
    """Create the Connector's required Custom Fields if they don't already exist.

    Returns the `dt.fieldname` identifiers of fields that were newly created.
    """
    created: list[str] = []
    for field in CUSTOM_FIELDS:
        existing = client.get_list(
            "Custom Field",
            filters={"dt": field["dt"], "fieldname": field["fieldname"]},
            fields=["name", "options", "read_only_depends_on"],
        )
        if existing:
            updates: dict[str, Any] = {}
            if field.get("fieldtype") == "Select" and existing[0].get("options") != field.get("options"):
                updates["options"] = field["options"]
            if (existing[0].get("read_only_depends_on") or "") != (field.get("read_only_depends_on") or ""):
                updates["read_only_depends_on"] = field.get("read_only_depends_on") or ""
            if updates:
                client.update({"doctype": "Custom Field", "name": existing[0]["name"], **updates})
                created.append(f"{field['dt']}.{field['fieldname']} (updated)")
            continue
        client.insert({"doctype": "Custom Field", **field})
        created.append(f"{field['dt']}.{field['fieldname']}")
    return created


def register_webhooks(client: ERPNextClientProtocol, base_url: str) -> list[str]:
    """Create or update Frappe Webhook configs pointing at the Connector, idempotently.

    Checks by doctype+docevent only (not URL) so that a changed CONNECTOR_BASE_URL
    updates the existing record rather than trying to insert a duplicate name.

    Returns the `DocType.docevent` identifiers of webhooks that were newly created
    or updated.
    """
    base = base_url.rstrip("/")
    created: list[str] = []
    for doctype, path, docevents in WEBHOOK_REGISTRATIONS:
        request_url = f"{base}{path}"
        for docevent in docevents:
            name = f"{doctype}-{docevent}"
            existing = client.get_list(
                "Webhook",
                filters={"webhook_doctype": doctype, "webhook_docevent": docevent},
                fields=["name", "request_url"],
            )
            if existing:
                if existing[0].get("request_url") == request_url:
                    continue
                client.update(
                    {
                        "doctype": "Webhook",
                        "name": existing[0]["name"],
                        "request_url": request_url,
                    }
                )
            else:
                client.insert(
                    {
                        "doctype": "Webhook",
                        # The Webhook DocType uses `autoname: prompt`, so a `name`
                        # must be supplied explicitly on insert.
                        "name": name,
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


def register_server_scripts(client: ERPNextClientProtocol, base_url: str) -> list[str]:
    """Create or update the Frappe Server Scripts the Connector requires.

    Frappe Webhooks don't support on_trash, so deletion propagation uses a
    Server Script instead.  Returns the names of scripts created or updated.
    """
    base = base_url.rstrip("/") + "/"
    scripts = [
        {
            "name": "Connector-Item-After-Delete",
            "script_type": "DocType Event",
            "dt": "Item",
            "doctype_event": "After Delete",
            "script": _ITEM_DELETE_SCRIPT.format(base_url=base),
            "disabled": 0,
        }
    ]
    created: list[str] = []
    for script in scripts:
        existing = client.get_list(
            "Server Script",
            filters={"name": script["name"]},
            fields=["name", "script"],
        )
        if existing:
            if existing[0].get("script") == script["script"]:
                continue
            client.update({"doctype": "Server Script", **script})
        else:
            client.insert({"doctype": "Server Script", **script})
        created.append(script["name"])
    return created


_CLIENT_SCRIPTS: list[dict[str, Any]] = [
    {
        "name": "Connector-Item-Form",
        "script_type": "Form",
        "dt": "Item",
        "script": _ITEM_FORM_CLIENT_SCRIPT,
        "enabled": 1,
    }
]


def register_client_scripts(client: ERPNextClientProtocol) -> list[str]:
    """Create or update the Frappe Client Scripts the Connector requires.

    These run in the browser and improve the Item form UX: auto-expanding
    the Description section and making the image field more prominent.
    Returns the names of scripts created or updated.
    """
    created: list[str] = []
    for script in _CLIENT_SCRIPTS:
        existing = client.get_list(
            "Client Script",
            filters={"name": script["name"]},
            fields=["name", "script"],
        )
        if existing:
            if existing[0].get("script") == script["script"]:
                continue
            client.update({"doctype": "Client Script", **script})
        else:
            client.insert({"doctype": "Client Script", **script})
        created.append(script["name"])
    return created


def main() -> None:
    settings = get_settings()
    client = ERPNextClient(settings)

    created_fields = register_custom_fields(client)
    created_webhooks = register_webhooks(client, settings.connector_base_url)
    created_scripts = register_server_scripts(client, settings.connector_base_url)
    created_client_scripts = register_client_scripts(client)

    if created_fields:
        print(f"Created Custom Fields: {', '.join(created_fields)}")
    else:
        print("All Custom Fields already exist.")

    if created_webhooks:
        print(f"Created Webhooks: {', '.join(created_webhooks)}")
    else:
        print("All Webhooks already exist.")

    if created_scripts:
        print(f"Created/updated Server Scripts: {', '.join(created_scripts)}")
    else:
        print("All Server Scripts already exist.")

    if created_client_scripts:
        print(f"Created/updated Client Scripts: {', '.join(created_client_scripts)}")
    else:
        print("All Client Scripts already exist.")


if __name__ == "__main__":
    main()
