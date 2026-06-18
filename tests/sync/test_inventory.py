import pytest
from sqlmodel import Session, SQLModel, create_engine

from connector.sync.inventory import handle_stock_webhook, push_item_inventory, seed_inventory_entity
from tests.erpnext.fakes import FakeERPNextClient
from tests.shopify.fakes import FakeShopifyClient

WAREHOUSE = "Stores - TC"
LOCATION_GID = "gid://shopify/Location/1"


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _item(client, name, *, variant_of=None, inv_gid=""):
    return client.insert({
        "doctype": "Item",
        "name": name,
        "item_code": name,
        "variant_of": variant_of,
        "has_variants": 1 if (not variant_of and not inv_gid) else 0,
        "shopify_inventory_item_gid": inv_gid,
        "shopify_variant_gid": f"gid://shopify/ProductVariant/{name}" if inv_gid else "",
    })


def _bin(client, item_code, qty):
    client.insert({
        "doctype": "Bin",
        "name": f"{item_code}::{WAREHOUSE}",
        "item_code": item_code,
        "warehouse": WAREHOUSE,
        "actual_qty": qty,
    })


# ── standalone item ───────────────────────────────────────────────────────────

def test_stock_webhook_sets_qty_on_standalone_item(session):
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    inv_gid = "gid://shopify/InventoryItem/10"
    _item(client, "BOOK-001", inv_gid=inv_gid)
    _bin(client, "BOOK-001", 42)
    seed_inventory_entity(session, inv_gid, "gid://shopify/Product/1", "BOOK-001")

    payload = {"items": [{"item_code": "BOOK-001", "warehouse": WAREHOUSE}]}
    handle_stock_webhook(session, shopify, client, payload)

    assert client.get_doc("Item", "BOOK-001")["connector_available_qty"] == 42


def test_stock_webhook_qty_zero_when_no_bin(session):
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    inv_gid = "gid://shopify/InventoryItem/11"
    _item(client, "BOOK-002", inv_gid=inv_gid)
    seed_inventory_entity(session, inv_gid, "gid://shopify/Product/2", "BOOK-002")

    payload = {"items": [{"item_code": "BOOK-002", "warehouse": WAREHOUSE}]}
    handle_stock_webhook(session, shopify, client, payload)

    assert client.get_doc("Item", "BOOK-002")["connector_available_qty"] == 0


# ── variant item updates parent template ──────────────────────────────────────

def test_stock_webhook_updates_parent_template_total(session):
    """When a variant's stock changes, the parent template gets the sum of all variants."""
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    _item(client, "SHIRT")  # template
    inv_s = "gid://shopify/InventoryItem/20"
    inv_m = "gid://shopify/InventoryItem/21"
    _item(client, "SHIRT-S", variant_of="SHIRT", inv_gid=inv_s)
    _item(client, "SHIRT-M", variant_of="SHIRT", inv_gid=inv_m)
    _bin(client, "SHIRT-S", 10)
    _bin(client, "SHIRT-M", 15)

    seed_inventory_entity(session, inv_s, "gid://shopify/Product/3", "SHIRT-S")
    seed_inventory_entity(session, inv_m, "gid://shopify/Product/3", "SHIRT-M")

    payload = {"items": [{"item_code": "SHIRT-S", "warehouse": WAREHOUSE}]}
    handle_stock_webhook(session, shopify, client, payload)

    assert client.get_doc("Item", "SHIRT-S")["connector_available_qty"] == 10
    assert client.get_doc("Item", "SHIRT")["connector_available_qty"] == 25  # 10 + 15


def test_push_item_inventory_sets_qty(session):
    """push_item_inventory (used on initial sync) also populates the field."""
    client = FakeERPNextClient()
    shopify = FakeShopifyClient()

    inv_gid = "gid://shopify/InventoryItem/30"
    _item(client, "MUG-001", inv_gid=inv_gid)
    _bin(client, "MUG-001", 7)
    seed_inventory_entity(session, inv_gid, "gid://shopify/Product/4", "MUG-001")

    push_item_inventory(session, shopify, client, "MUG-001")

    assert client.get_doc("Item", "MUG-001")["connector_available_qty"] == 7
