from typing import Any
from unittest.mock import MagicMock

import pytest

from connector.config import get_settings
from connector.erpnext.client import ERPNextClient


@pytest.fixture
def client(monkeypatch) -> tuple[ERPNextClient, MagicMock]:
    fake_frappe = MagicMock()
    monkeypatch.setattr("connector.erpnext.client.FrappeClient", MagicMock(return_value=fake_frappe))
    return ERPNextClient(get_settings()), fake_frappe


def test_get_doc_delegates_to_frappeclient(client: tuple[ERPNextClient, MagicMock]) -> None:
    erpnext_client, fake_frappe = client
    fake_frappe.get_doc.return_value = {"name": "ITEM-001", "item_code": "ITEM-001"}

    result = erpnext_client.get_doc("Item", "ITEM-001")

    fake_frappe.get_doc.assert_called_once_with("Item", "ITEM-001")
    assert result == {"name": "ITEM-001", "item_code": "ITEM-001"}


def test_get_list_defaults_fields_to_all(client: tuple[ERPNextClient, MagicMock]) -> None:
    erpnext_client, fake_frappe = client
    fake_frappe.get_list.return_value = []

    erpnext_client.get_list("Item", filters={"disabled": 0})

    fake_frappe.get_list.assert_called_once_with(
        "Item", fields=["*"], filters={"disabled": 0}, limit_page_length=0
    )


def test_insert_delegates_to_frappeclient(client: tuple[ERPNextClient, MagicMock]) -> None:
    erpnext_client, fake_frappe = client
    doc: dict[str, Any] = {"doctype": "Item", "item_code": "ITEM-001"}
    fake_frappe.insert.return_value = {**doc, "name": "ITEM-001"}

    result = erpnext_client.insert(doc)

    fake_frappe.insert.assert_called_once_with(doc)
    assert result["name"] == "ITEM-001"


def test_submit_and_cancel_delegate_to_frappeclient(client: tuple[ERPNextClient, MagicMock]) -> None:
    erpnext_client, fake_frappe = client
    doc = {"doctype": "Delivery Note", "name": "DN-001"}

    erpnext_client.submit(doc)
    erpnext_client.cancel("Delivery Note", "DN-001")

    fake_frappe.submit.assert_called_once_with(doc)
    fake_frappe.cancel.assert_called_once_with("Delivery Note", "DN-001")
