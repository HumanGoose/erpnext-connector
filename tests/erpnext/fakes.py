from collections import defaultdict
from typing import Any


class FakeERPNextClient:
    """In-memory stand-in for `ERPNextClientProtocol`, for sync-handler and setup tests."""

    def __init__(self) -> None:
        self.docs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._counters: dict[str, int] = defaultdict(int)

    def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        for doc in self.docs[doctype]:
            if doc.get("name") == name:
                return doc
        raise LookupError(f"{doctype} {name} not found")

    def get_list(
        self,
        doctype: str,
        filters: dict[str, Any] | list[Any] | None = None,
        fields: list[str] | None = None,
        limit_page_length: int = 0,
    ) -> list[dict[str, Any]]:
        records = self.docs[doctype]
        if isinstance(filters, dict):
            records = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
        if limit_page_length:
            records = records[:limit_page_length]
        return [dict(r) for r in records]

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        record = dict(doc)
        if not record.get("name"):
            self._counters[record["doctype"]] += 1
            record["name"] = f"{record['doctype']}-{self._counters[record['doctype']]}"
        record.setdefault("docstatus", 0)
        self.docs[record["doctype"]].append(record)
        return record

    def update(self, doc: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_doc(doc["doctype"], doc["name"])
        existing.update(doc)
        return existing

    def delete(self, doctype: str, name: str) -> None:
        self.docs[doctype] = [d for d in self.docs[doctype] if d.get("name") != name]

    def submit(self, doc: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_doc(doc["doctype"], doc["name"])
        existing["docstatus"] = 1
        return existing

    def cancel(self, doctype: str, name: str) -> dict[str, Any]:
        existing = self.get_doc(doctype, name)
        existing["docstatus"] = 2
        return existing

    def set_value(self, doctype: str, name: str, fieldname: str, value: Any) -> dict[str, Any]:
        existing = self.get_doc(doctype, name)
        existing[fieldname] = value
        return existing
