from fastapi.testclient import TestClient
from sqlmodel import Session

from connector.db import engine
from connector.main import app
from connector.models import EntityType, RetryQueueEntry, RetryStatus, SyncDirection, SyncedEntity


def _seed() -> None:
    with Session(engine) as session:
        session.add(SyncedEntity(entity_type=EntityType.PRODUCT, shopify_gid="gid://shopify/Product/1"))
        session.add(SyncedEntity(entity_type=EntityType.CUSTOMER, shopify_gid="gid://shopify/Customer/1"))
        session.add(
            RetryQueueEntry(
                direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
                entity_type=EntityType.PRODUCT,
                payload="{}",
                status=RetryStatus.PENDING,
            )
        )
        session.add(
            RetryQueueEntry(
                direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
                entity_type=EntityType.ORDER,
                payload="{}",
                status=RetryStatus.DEAD_LETTER,
                last_error="boom",
            )
        )
        session.commit()


def test_list_synced_entities_returns_all_and_filters_by_entity_type():
    with TestClient(app) as client:
        _seed()

        response = client.get("/status/synced-entities")
        assert response.status_code == 200
        entity_types = {row["entity_type"] for row in response.json()}
        assert {"product", "customer"} <= entity_types

        response = client.get("/status/synced-entities", params={"entity_type": "product"})
        assert response.status_code == 200
        rows = response.json()
        assert rows
        assert all(row["entity_type"] == "product" for row in rows)


def test_list_retry_queue_filters_by_status_and_entity_type():
    with TestClient(app) as client:
        _seed()

        response = client.get("/status/retry-queue", params={"status": "dead_letter"})
        assert response.status_code == 200
        rows = response.json()
        assert rows
        assert all(row["status"] == "dead_letter" for row in rows)
        assert any(row["last_error"] == "boom" for row in rows)

        response = client.get("/status/retry-queue", params={"entity_type": "order"})
        assert response.status_code == 200
        rows = response.json()
        assert rows
        assert all(row["entity_type"] == "order" for row in rows)
