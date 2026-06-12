from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from connector.db import get_session
from connector.models import SyncedEntity

router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    session.exec(select(SyncedEntity)).first()
    return {"status": "ok"}
