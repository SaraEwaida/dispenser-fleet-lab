from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.api.common import Page, PageParams, iso, page_params, paginate
from app.core.clock import get_clock
from app.core.errors import AppError, not_found
from app.core.security import require
from app.db.session import get_db
from app.models import Alert, AlertStatus, AlertType, Device, Severity, Ticket, User
from app.services.audit import audit

router = APIRouter(tags=["Alerts"])

SEVERITY_ORDER = case({Severity.critical: 0, Severity.high: 1, Severity.medium: 2, Severity.low: 3}, value=Alert.severity)


def alert_out(a: Alert, users: dict[int, str], now) -> dict:
    return {
        "id": a.id, "code": a.code, "type": a.type.value, "severity": a.severity.value, "status": a.status.value,
        "message": a.message, "created_at": iso(a.created_at), "ack_due_at": iso(a.ack_due_at),
        "overdue": a.status == AlertStatus.open and a.ack_due_at < now,
        "acknowledged_at": iso(a.acknowledged_at), "acknowledged_by": users.get(a.acknowledged_by),
        "resolved_at": iso(a.resolved_at), "resolved_by": users.get(a.resolved_by),
        "auto_resolved": a.auto_resolved, "resolution": a.resolution, "dose_id": a.dose_id,
        "device": {"serial": a.device.serial, "status": a.device.status.value, "client_code": a.device.client.client_code,
                   "client_name": a.device.client.display_name, "care_team": a.device.client.care_team},
    }


def _users(db: Session) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.full_name)).all())


@router.get("/alerts", response_model=Page[dict])
def list_alerts(
    status: list[AlertStatus] | None = Query(None), severity: Severity | None = None, type: AlertType | None = None,
    serial: str | None = Query(None, max_length=20), overdue: bool | None = None,
    p: PageParams = Depends(page_params), _: User = Depends(require("alerts:read")), db: Session = Depends(get_db),
):
    now = get_clock().now()
    stmt = select(Alert).join(Device).options(joinedload(Alert.device).joinedload(Device.client))
    if status:
        stmt = stmt.where(Alert.status.in_(status))
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if type:
        stmt = stmt.where(Alert.type == type)
    if serial:
        stmt = stmt.where(Device.serial == serial.strip())
    if overdue:
        stmt = stmt.where(Alert.status == AlertStatus.open, Alert.ack_due_at < now)
    status_order = case({AlertStatus.open: 0, AlertStatus.acknowledged: 1, AlertStatus.resolved: 2}, value=Alert.status)
    stmt = stmt.order_by(status_order, SEVERITY_ORDER, Alert.created_at.desc())
    items, total = paginate(db, stmt, p)
    users = _users(db)
    return Page(items=[alert_out(a, users, now) for a in items], total=total, page=p.page, page_size=p.page_size)


def _load(db: Session, alert_id: int) -> Alert:
    a = db.scalars(select(Alert).where(Alert.id == alert_id).options(joinedload(Alert.device).joinedload(Device.client))
                   .with_for_update(of=Alert)).first()
    if a is None:
        raise not_found("Alert")
    return a


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: int, _: User = Depends(require("alerts:read")), db: Session = Depends(get_db)):
    a = _load(db, alert_id)
    tickets = db.execute(select(Ticket.id, Ticket.code, Ticket.status).where(Ticket.alert_id == a.id)).all()
    return {**alert_out(a, _users(db), get_clock().now()),
            "tickets": [{"id": i, "code": c, "status": s.value} for i, c, s in tickets]}


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: int, user: User = Depends(require("alerts:handle")), db: Session = Depends(get_db)):
    a = _load(db, alert_id)
    if a.status != AlertStatus.open:
        raise AppError(409, "INVALID_TRANSITION", f"Alert is already {a.status.value}.")
    now = get_clock().now()
    a.status, a.acknowledged_at, a.acknowledged_by = AlertStatus.acknowledged, now, user.id
    audit(db, user, "acknowledge", "alert", a.code, {"late": a.ack_due_at < now})
    db.commit()
    return alert_out(a, _users(db), now)


class ResolveIn(BaseModel):
    resolution: str = Field(min_length=5, max_length=500)


@router.post("/alerts/{alert_id}/resolve")
def resolve(alert_id: int, body: ResolveIn, user: User = Depends(require("alerts:handle")), db: Session = Depends(get_db)):
    a = _load(db, alert_id)
    if a.status == AlertStatus.resolved:
        raise AppError(409, "INVALID_TRANSITION", "Alert is already resolved.")
    now = get_clock().now()
    if a.status == AlertStatus.open:  # resolving implies acknowledging
        a.acknowledged_at, a.acknowledged_by = now, user.id
    a.status, a.resolved_at, a.resolved_by, a.resolution = AlertStatus.resolved, now, user.id, body.resolution.strip()
    audit(db, user, "resolve", "alert", a.code)
    db.commit()
    return alert_out(a, _users(db), now)
