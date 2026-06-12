from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from connector.db import get_session
from connector.models import EntityType, RetryQueueEntry, RetryStatus, SyncedEntity

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/synced-entities")
def list_synced_entities(
    entity_type: EntityType | None = None,
    session: Session = Depends(get_session),
) -> list[SyncedEntity]:
    statement = select(SyncedEntity)
    if entity_type is not None:
        statement = statement.where(SyncedEntity.entity_type == entity_type)
    return list(session.exec(statement).all())


@router.get("/retry-queue")
def list_retry_queue(
    status: RetryStatus | None = None,
    entity_type: EntityType | None = None,
    session: Session = Depends(get_session),
) -> list[RetryQueueEntry]:
    statement = select(RetryQueueEntry)
    if status is not None:
        statement = statement.where(RetryQueueEntry.status == status)
    if entity_type is not None:
        statement = statement.where(RetryQueueEntry.entity_type == entity_type)
    return list(session.exec(statement).all())
