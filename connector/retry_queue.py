from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from connector.config import get_settings
from connector.models import EntityType, RetryQueueEntry, RetryStatus, SyncDirection


def _utcnow() -> datetime:
    # Naive UTC: SQLite round-trips datetimes without tzinfo, and comparisons
    # against freshly-loaded `next_attempt_at` values need to match that.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(
    session: Session,
    *,
    direction: SyncDirection,
    entity_type: EntityType,
    payload: str,
    synced_entity_id: int | None = None,
) -> RetryQueueEntry:
    """Insert a `pending` Retry Queue row for a sync operation."""
    entry = RetryQueueEntry(
        synced_entity_id=synced_entity_id,
        direction=direction,
        entity_type=entity_type,
        payload=payload,
        status=RetryStatus.PENDING,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def record_failure(
    session: Session,
    entry: RetryQueueEntry,
    error: str,
    *,
    max_attempts: int | None = None,
    base_delay_seconds: int | None = None,
) -> RetryQueueEntry:
    """Record a failed processing attempt.

    Increments `attempt_count` and records `last_error`. If the new
    `attempt_count` reaches `max_attempts`, the entry transitions to
    `dead_letter` (retaining `last_error`); otherwise it stays `pending`
    with `next_attempt_at` pushed out by exponential backoff.
    """
    settings = get_settings()
    if max_attempts is None:
        max_attempts = settings.retry_max_attempts
    if base_delay_seconds is None:
        base_delay_seconds = settings.retry_base_delay_seconds

    entry.attempt_count += 1
    entry.last_error = error

    if entry.attempt_count >= max_attempts:
        entry.status = RetryStatus.DEAD_LETTER
        entry.next_attempt_at = None
    else:
        entry.status = RetryStatus.PENDING
        delay = base_delay_seconds * (2 ** (entry.attempt_count - 1))
        entry.next_attempt_at = _utcnow() + timedelta(seconds=delay)

    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def record_success(session: Session, entry: RetryQueueEntry) -> RetryQueueEntry:
    """Mark an entry as `completed` after a successful processing attempt."""
    entry.status = RetryStatus.COMPLETED
    entry.next_attempt_at = None
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry
