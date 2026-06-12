from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel


class EntityType(str, Enum):
    PRODUCT = "product"
    VARIANT = "variant"
    IMAGE = "image"
    CUSTOMER = "customer"
    ORDER = "order"
    FULFILLMENT = "fulfillment"
    INVENTORY_LEVEL = "inventory_level"


class SyncDirection(str, Enum):
    SHOPIFY_TO_ERPNEXT = "shopify_to_erpnext"
    ERPNEXT_TO_SHOPIFY = "erpnext_to_shopify"


class RetryStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DEAD_LETTER = "dead_letter"
    COMPLETED = "completed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SyncedEntity(SQLModel, table=True):
    """One row per Shopify<->ERPNext record pairing (per PRD conceptual schema)."""

    id: int | None = Field(default=None, primary_key=True)
    entity_type: EntityType
    group_key: str | None = Field(default=None, index=True)
    shopify_gid: str | None = Field(default=None, index=True)
    erpnext_doctype: str | None = None
    erpnext_name: str | None = None
    shopify_fingerprint: str | None = None
    erpnext_fingerprint: str | None = None
    last_synced_at: datetime | None = None


class RetryQueueEntry(SQLModel, table=True):
    """One row per pending/failed sync operation (per PRD conceptual schema)."""

    __tablename__ = "retry_queue"

    id: int | None = Field(default=None, primary_key=True)
    synced_entity_id: int | None = Field(default=None, foreign_key="syncedentity.id")
    direction: SyncDirection
    entity_type: EntityType
    payload: str
    attempt_count: int = Field(default=0)
    next_attempt_at: datetime | None = None
    status: RetryStatus = Field(default=RetryStatus.PENDING)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
