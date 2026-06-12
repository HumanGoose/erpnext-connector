from datetime import datetime, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine

from connector.config import get_settings
from connector.models import EntityType, RetryStatus, SyncDirection
from connector.retry_queue import enqueue, record_failure, record_success


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_enqueue_inserts_pending_entry(session):
    entry = enqueue(
        session,
        direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
        entity_type=EntityType.PRODUCT,
        payload='{"id": "gid://shopify/Product/1"}',
    )

    assert entry.id is not None
    assert entry.status == RetryStatus.PENDING
    assert entry.attempt_count == 0
    assert entry.synced_entity_id is None
    assert entry.payload == '{"id": "gid://shopify/Product/1"}'


def test_enqueue_links_synced_entity():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        entry = enqueue(
            session,
            direction=SyncDirection.ERPNEXT_TO_SHOPIFY,
            entity_type=EntityType.ORDER,
            payload="{}",
            synced_entity_id=42,
        )

    assert entry.synced_entity_id == 42


def test_record_failure_applies_exponential_backoff(session):
    entry = enqueue(
        session,
        direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
        entity_type=EntityType.PRODUCT,
        payload="{}",
    )

    first = record_failure(session, entry, "boom", max_attempts=5, base_delay_seconds=60)
    assert first.status == RetryStatus.PENDING
    assert first.attempt_count == 1
    assert first.last_error == "boom"
    assert (first.next_attempt_at - _utcnow()).total_seconds() == pytest.approx(60, abs=2)

    second = record_failure(session, entry, "boom again", max_attempts=5, base_delay_seconds=60)
    assert second.attempt_count == 2
    assert second.last_error == "boom again"
    assert (second.next_attempt_at - _utcnow()).total_seconds() == pytest.approx(120, abs=2)


def test_record_failure_moves_to_dead_letter_after_max_attempts(session):
    entry = enqueue(
        session,
        direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
        entity_type=EntityType.PRODUCT,
        payload="{}",
    )

    for _ in range(2):
        entry = record_failure(session, entry, "boom", max_attempts=3, base_delay_seconds=1)
    assert entry.status == RetryStatus.PENDING

    entry = record_failure(session, entry, "final boom", max_attempts=3, base_delay_seconds=1)

    assert entry.status == RetryStatus.DEAD_LETTER
    assert entry.attempt_count == 3
    assert entry.last_error == "final boom"
    assert entry.next_attempt_at is None


def test_record_failure_uses_configured_defaults(session):
    settings = get_settings()
    entry = enqueue(
        session,
        direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
        entity_type=EntityType.PRODUCT,
        payload="{}",
    )

    for _ in range(settings.retry_max_attempts - 1):
        entry = record_failure(session, entry, "boom")
    assert entry.status == RetryStatus.PENDING

    entry = record_failure(session, entry, "final boom")
    assert entry.status == RetryStatus.DEAD_LETTER
    assert entry.attempt_count == settings.retry_max_attempts


def test_record_success_marks_completed(session):
    entry = enqueue(
        session,
        direction=SyncDirection.SHOPIFY_TO_ERPNEXT,
        entity_type=EntityType.PRODUCT,
        payload="{}",
    )

    completed = record_success(session, entry)

    assert completed.status == RetryStatus.COMPLETED
    assert completed.next_attempt_at is None
