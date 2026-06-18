import json
import time
from functools import lru_cache
from typing import Any, Protocol

import requests as _requests
from frappeclient import FrappeClient

from connector.config import Settings, get_settings

_DEADLOCK_RETRIES = 3
_DEADLOCK_DELAY = 0.5  # seconds between retries


def _is_retryable(exc: Exception) -> bool:
    """Returns True for transient ERPNext write errors worth retrying.

    Two shapes:
    - frappeclient raises JSONDecodeError when ERPNext returns a 500 HTML page
      (the deadlock error page rendered by Frappe's exception handler).
    - FrappeException / raw string contains the MySQL error 1020 text.
    """
    if isinstance(exc, (json.JSONDecodeError, _requests.exceptions.JSONDecodeError)):
        return True
    msg = str(exc)
    return "1020" in msg or "QueryDeadlockError" in msg or "Record has changed since last read" in msg


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
        last_exc: Exception | None = None
        for attempt in range(_DEADLOCK_RETRIES):
            try:
                return self._client.insert(doc)
            except Exception as exc:
                if _is_retryable(exc):
                    last_exc = exc
                    time.sleep(_DEADLOCK_DELAY * (attempt + 1))
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    def update(self, doc: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(_DEADLOCK_RETRIES):
            try:
                return self._client.update(doc)
            except Exception as exc:
                if _is_retryable(exc):
                    last_exc = exc
                    time.sleep(_DEADLOCK_DELAY * (attempt + 1))
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    def delete(self, doctype: str, name: str) -> None:
        self._client.delete(doctype, name)

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Submit a Frappe document (docstatus → 1).

        frappeclient.submit() crashes with JSONDecodeError when Frappe returns
        an empty or non-JSON body (observed in Frappe v15 on Stock Reconciliation
        submit). We fall back to calling frappe.client.submit directly via the
        method API, which is the correct Frappe endpoint for submitting docs
        (the resource PUT endpoint rejects docstatus changes with 417).
        """
        try:
            result = self._client.submit(doc)
            return result if isinstance(result, dict) else doc
        except (json.JSONDecodeError, _requests.exceptions.JSONDecodeError, ValueError, IOError):
            pass

        name = doc.get("name")
        doctype = doc.get("doctype")
        if not name or not doctype:
            raise RuntimeError(f"Cannot submit doc without doctype/name: {doc}")

        url = f"{self._client.url}/api/method/frappe.client.submit"
        resp = self._client.session.post(
            url,
            data={"doc": json.dumps({**doc, "docstatus": 1})},
            verify=self._client.verify,
        )
        try:
            resp.raise_for_status()
            return resp.json().get("message") or doc
        except Exception:
            # If the method API also returns empty/error, verify docstatus directly.
            current = self.get_doc(doctype, name)
            if current.get("docstatus") == 1:
                return current
            raise RuntimeError(f"Submit failed for {doctype} {name}: response was {resp.status_code} {resp.text[:200]}")

    def cancel(self, doctype: str, name: str) -> dict[str, Any]:
        return self._client.cancel(doctype, name)

    def set_value(self, doctype: str, name: str, fieldname: str, value: Any) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(_DEADLOCK_RETRIES):
            try:
                return self._client.set_value(doctype, name, fieldname, value)
            except Exception as exc:
                if _is_retryable(exc):
                    last_exc = exc
                    time.sleep(_DEADLOCK_DELAY * (attempt + 1))
                    continue
                raise
        raise last_exc  # type: ignore[misc]


@lru_cache
def get_erpnext_client() -> ERPNextClientProtocol:
    """FastAPI dependency: a shared `ERPNextClient` instance.

    Tests override this dependency with a `FakeERPNextClient`.
    """
    return ERPNextClient(get_settings())
