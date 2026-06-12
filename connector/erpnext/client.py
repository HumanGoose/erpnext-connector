from functools import lru_cache
from typing import Any, Protocol

from frappeclient import FrappeClient

from connector.config import Settings, get_settings


class ERPNextClientProtocol(Protocol):
    """The subset of `frappeclient.FrappeClient` the Connector depends on.

    Sync handler tests fake this interface (per the PRD's Testing Decisions)
    instead of hitting a real ERPNext instance.
    """

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]: ...

    def get_list(
        self,
        doctype: str,
        filters: dict[str, Any] | list[Any] | None = None,
        fields: list[str] | None = None,
        limit_page_length: int = 0,
    ) -> list[dict[str, Any]]: ...

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]: ...

    def update(self, doc: dict[str, Any]) -> dict[str, Any]: ...

    def delete(self, doctype: str, name: str) -> None: ...

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]: ...

    def cancel(self, doctype: str, name: str) -> dict[str, Any]: ...

    def set_value(self, doctype: str, name: str, fieldname: str, value: Any) -> dict[str, Any]: ...


class ERPNextClient:
    """Thin wrapper around `frappeclient.FrappeClient` implementing `ERPNextClientProtocol`."""

    def __init__(self, settings: Settings) -> None:
        self._client = FrappeClient(
            url=settings.erpnext_url,
            api_key=settings.erpnext_api_key,
            api_secret=settings.erpnext_api_secret,
        )

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        return self._client.get_doc(doctype, name)

    def get_list(
        self,
        doctype: str,
        filters: dict[str, Any] | list[Any] | None = None,
        fields: list[str] | None = None,
        limit_page_length: int = 0,
    ) -> list[dict[str, Any]]:
        return self._client.get_list(
            doctype,
            fields=fields or ["*"],
            filters=filters,
            limit_page_length=limit_page_length,
        )

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        return self._client.insert(doc)

    def update(self, doc: dict[str, Any]) -> dict[str, Any]:
        return self._client.update(doc)

    def delete(self, doctype: str, name: str) -> None:
        self._client.delete(doctype, name)

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
        return self._client.submit(doc)

    def cancel(self, doctype: str, name: str) -> dict[str, Any]:
        return self._client.cancel(doctype, name)

    def set_value(self, doctype: str, name: str, fieldname: str, value: Any) -> dict[str, Any]:
        return self._client.set_value(doctype, name, fieldname, value)


@lru_cache
def get_erpnext_client() -> ERPNextClientProtocol:
    """FastAPI dependency: a shared `ERPNextClient` instance.

    Tests override this dependency with a `FakeERPNextClient`.
    """
    return ERPNextClient(get_settings())
