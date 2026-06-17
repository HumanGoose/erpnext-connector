from connector.erpnext.setup import (
    CUSTOM_FIELDS,
    WEBHOOK_REGISTRATIONS,
    register_custom_fields,
    register_webhooks,
)
from tests.erpnext.fakes import FakeERPNextClient


def test_register_custom_fields_creates_all_fields():
    client = FakeERPNextClient()

    created = register_custom_fields(client)

    assert len(created) == len(CUSTOM_FIELDS)
    custom_fields = client.get_list("Custom Field")
    assert len(custom_fields) == len(CUSTOM_FIELDS)
    assert {(f["dt"], f["fieldname"]) for f in custom_fields} == {
        (f["dt"], f["fieldname"]) for f in CUSTOM_FIELDS
    }


def test_register_custom_fields_is_idempotent():
    client = FakeERPNextClient()

    register_custom_fields(client)
    second_pass = register_custom_fields(client)

    assert second_pass == []
    assert len(client.get_list("Custom Field")) == len(CUSTOM_FIELDS)


def test_register_webhooks_creates_expected_doctype_event_pairs():
    client = FakeERPNextClient()
    base_url = "https://connector.example.com"

    created = register_webhooks(client, base_url)

    expected = {
        f"{doctype}.{docevent}"
        for doctype, _, docevents in WEBHOOK_REGISTRATIONS
        for docevent in docevents
    }
    assert set(created) == expected

    webhooks = client.get_list("Webhook")
    assert len(webhooks) == len(expected)
    # Every registered path must appear as a request_url.
    registered_urls = {f"{base_url}{path}" for _, path, _ in WEBHOOK_REGISTRATIONS}
    assert all(w["request_url"] in registered_urls for w in webhooks)


def test_register_webhooks_is_idempotent():
    client = FakeERPNextClient()
    base_url = "https://connector.example.com"

    register_webhooks(client, base_url)
    second_pass = register_webhooks(client, base_url)

    assert second_pass == []
