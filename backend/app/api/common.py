from datetime import datetime
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.models import Device

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class PageParams(BaseModel):
    page: int
    page_size: int


def page_params(page: int = Query(1, ge=1, le=10_000), page_size: int = Query(25, ge=1, le=200)) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def paginate(db: Session, stmt: Select, p: PageParams) -> tuple[list, int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    return list(db.scalars(stmt.offset((p.page - 1) * p.page_size).limit(p.page_size)).unique()), total


def get_device(db: Session, serial: str, lock: bool = False) -> Device:
    stmt = select(Device).where(Device.serial == serial)
    if lock:
        stmt = stmt.with_for_update()
    d = db.scalars(stmt).first()
    if d is None:
        raise not_found("Device")
    return d


def iso(v: datetime | None) -> str | None:
    return v.isoformat() if v else None
