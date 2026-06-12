"""Shared Synced Entity helpers used by every sync handler.

Centralizes the Synced Entity lookups, upsert, and GID normalization that the
per-entity sync modules build on, so Echo detection and Fingerprint bookkeeping
behave identically across directions and entity types.
"""

from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from connector.models import EntityType, SyncedEntity


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_by_shopify_gid(session: Session, entity_type: EntityType, shopify_gid: str) -> SyncedEntity | None:
    statement = select(SyncedEntity).where(
        SyncedEntity.entity_type == entity_type,
        SyncedEntity.shopify_gid == shopify_gid,
    )
    return session.exec(statement).first()


def get_by_erpnext(session: Session, entity_type: EntityType, doctype: str, name: str) -> SyncedEntity | None:
    statement = select(SyncedEntity).where(
        SyncedEntity.entity_type == entity_type,
        SyncedEntity.erpnext_doctype == doctype,
        SyncedEntity.erpnext_name == name,
    )
    return session.exec(statement).first()


def get_group(session: Session, group_key: str, entity_type: EntityType | None = None) -> list[SyncedEntity]:
    statement = select(SyncedEntity).where(SyncedEntity.group_key == group_key)
    if entity_type is not None:
        statement = statement.where(SyncedEntity.entity_type == entity_type)
    return list(session.exec(statement).all())


def save(session: Session, entity: SyncedEntity | None, **fields: Any) -> SyncedEntity:
    if entity is None:
        entity = SyncedEntity(**fields)
    else:
        for key, value in fields.items():
            setattr(entity, key, value)
    entity.last_synced_at = utcnow()
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity
