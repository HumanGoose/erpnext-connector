"""Customer sync in both directions (issues 15, 16).

Customers sync unconditionally (no opt-in flag, per PRD). Tracked fields are
name, email, phone, and addresses. The single system-agnostic `customer`
canonical drives Echo detection on both sides.

Note: ERPNext models a Customer's email/phone/addresses on linked Contact and
Address doctypes. To keep the round-trip Fingerprint symmetric (and the sync
handlers testable against fakes), the Connector denormalizes those onto the
Customer doc it writes; mapping them to real Contact/Address docs is deferred
to the manual e2e pass (issue 24).
"""

from typing import Any

from sqlmodel import Session

from connector.erpnext.client import ERPNextClientProtocol
from connector.fingerprint import canonicalize, fingerprint
from connector.models import EntityType
from connector.shopify.client import ShopifyClientProtocol
from connector.sync import entities


def _gid(raw: dict[str, Any]) -> str:
    gid = raw.get("admin_graphql_api_id") or raw.get("id")
    if gid is None:
        raise ValueError("Shopify customer is missing 'id'/'admin_graphql_api_id'")
    if isinstance(gid, str) and gid.startswith("gid://"):
        return gid
    return f"gid://shopify/Customer/{gid}"


def _erpnext_customer_doc(canonical: dict[str, Any], gid: str) -> dict[str, Any]:
    return {
        "doctype": "Customer",
        "customer_name": canonical["name"],
        "customer_type": "Individual",
        "email_id": canonical["email"],
        "mobile_no": canonical["phone"],
        "addresses": canonical["addresses"],
        "shopify_customer_gid": gid,
    }


def handle_shopify_customer_webhook(
    session: Session,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """Shopify Customer create/update -> ERPNext Customer (issue 15)."""
    gid = _gid(payload)
    canonical = canonicalize(EntityType.CUSTOMER, payload)
    fp = fingerprint(canonical)

    entity = entities.get_by_shopify_gid(session, EntityType.CUSTOMER, gid)
    if entity is not None and entity.shopify_fingerprint == fp:
        return  # Echo: our own prior write (issue 16).

    doc = _erpnext_customer_doc(canonical, gid)
    if entity is None or entity.erpnext_name is None:
        result = erpnext_client.insert(doc)
        name = result["name"]
    else:
        name = entity.erpnext_name
        erpnext_client.update({**doc, "name": name})

    entities.save(
        session,
        entity,
        entity_type=EntityType.CUSTOMER,
        shopify_gid=gid,
        group_key=gid,
        erpnext_doctype="Customer",
        erpnext_name=name,
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )


def _shopify_customer_input(canonical: dict[str, Any]) -> dict[str, Any]:
    first, _, last = canonical["name"].partition(" ")
    customer_input: dict[str, Any] = {"firstName": first, "lastName": last}
    if canonical["email"]:
        customer_input["email"] = canonical["email"]
    if canonical["phone"]:
        customer_input["phone"] = canonical["phone"]
    if canonical["addresses"]:
        customer_input["addresses"] = [
            {
                "address1": addr["address1"],
                "address2": addr["address2"],
                "city": addr["city"],
                "province": addr["province"],
                "country": addr["country"],
                "zip": addr["zip"],
            }
            for addr in canonical["addresses"]
        ]
    return customer_input


def handle_erpnext_customer_webhook(
    session: Session,
    shopify_client: ShopifyClientProtocol,
    erpnext_client: ERPNextClientProtocol,
    payload: dict[str, Any],
) -> None:
    """ERPNext Customer create/update -> Shopify Customer (issue 16)."""
    name = payload.get("name") or payload.get("customer_name")
    canonical = canonicalize(EntityType.CUSTOMER, payload)
    fp = fingerprint(canonical)

    entity = entities.get_by_erpnext(session, EntityType.CUSTOMER, "Customer", name)
    if entity is not None and entity.erpnext_fingerprint == fp:
        return  # Echo: our own prior write (issue 15).

    customer_input = _shopify_customer_input(canonical)
    if entity is None or not payload.get("shopify_customer_gid"):
        customer = shopify_client.create_customer(customer_input)
        gid = customer["id"]
        erpnext_client.set_value("Customer", name, "shopify_customer_gid", gid)
    else:
        gid = payload["shopify_customer_gid"]
        shopify_client.update_customer(gid, customer_input)

    entities.save(
        session,
        entity,
        entity_type=EntityType.CUSTOMER,
        shopify_gid=gid,
        group_key=gid,
        erpnext_doctype="Customer",
        erpnext_name=name,
        shopify_fingerprint=fp,
        erpnext_fingerprint=fp,
    )
