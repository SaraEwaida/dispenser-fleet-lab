from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.api.common import Page, PageParams, iso, page_params, paginate
from app.core.clock import get_clock
from app.core.security import require
from app.db.session import get_db
from app.models import (
    Alert, AlertStatus, AuditLog, Command, CommandStatus, Device, DeviceStatus, Dose, DoseStatus, Severity, Telemetry,
    TelemetryStatus, User,
)

router = APIRouter(tags=["Fleet, message log & audit"])


def telemetry_out(t: Telemetry) -> dict:
    return {"id": t.id, "msg_id": t.msg_id, "serial": t.serial, "type": t.type, "seq": t.seq, "device_ts": iso(t.device_ts),
            "received_at": iso(t.received_at), "status": t.status.value, "out_of_order": t.out_of_order,
            "buffered": t.buffered, "error": t.error, "payload": t.payload, "raw": t.raw}


@router.get("/messages", response_model=Page[dict])
def message_log(
    serial: str | None = Query(None, max_length=20), status: TelemetryStatus | None = None,
    type: str | None = Query(None, max_length=30), out_of_order: bool | None = None, buffered: bool | None = None,
    msg_id: str | None = Query(None, max_length=64),
    p: PageParams = Depends(page_params), _: User = Depends(require("telemetry:read")), db: Session = Depends(get_db),
):
    stmt = select(Telemetry).order_by(Telemetry.id.desc())
    if serial:
        stmt = stmt.where(Telemetry.serial == serial.strip())
    if status:
        stmt = stmt.where(Telemetry.status == status)
    if type:
        stmt = stmt.where(Telemetry.type == type)
    if out_of_order is not None:
        stmt = stmt.where(Telemetry.out_of_order == out_of_order)
    if buffered is not None:
        stmt = stmt.where(Telemetry.buffered == buffered)
    if msg_id:
        stmt = stmt.where(Telemetry.msg_id == msg_id.strip())
    items, total = paginate(db, stmt, p)
    return Page(items=[telemetry_out(t) for t in items], total=total, page=p.page, page_size=p.page_size)


@router.get("/fleet/summary")
def fleet_summary(_: User = Depends(require("fleet:read")), db: Session = Depends(get_db)):
    now = get_clock().now()
    day = now - timedelta(hours=24)
    hour = now - timedelta(hours=1)
    devices = dict(db.execute(select(Device.status, func.count()).where(Device.is_active).group_by(Device.status)).all())
    open_by_sev = dict(db.execute(select(Alert.severity, func.count()).where(Alert.status == AlertStatus.open)
                                  .group_by(Alert.severity)).all())
    acked = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.acknowledged)) or 0
    overdue = db.scalar(select(func.count()).select_from(Alert).where(Alert.status == AlertStatus.open, Alert.ack_due_at < now)) or 0
    doses = dict(db.execute(select(Dose.status, func.count()).where(Dose.due_at >= day, Dose.due_at <= now)
                            .group_by(Dose.status)).all())
    confirmed = doses.get(DoseStatus.taken, 0) + doses.get(DoseStatus.late, 0)
    counted = confirmed + doses.get(DoseStatus.missed, 0) + doses.get(DoseStatus.failed, 0)
    msgs = dict(db.execute(select(Telemetry.status, func.count()).where(Telemetry.received_at >= hour)
                           .group_by(Telemetry.status)).all())
    pending_cmds = db.scalar(select(func.count()).select_from(Command).where(
        Command.status.in_([CommandStatus.queued, CommandStatus.sent]))) or 0

    # Hourly dose outcomes for the last 24 simulated hours (chart).
    bucket = func.date_trunc("hour", Dose.due_at)
    series = {}
    for b, st, n in db.execute(select(bucket, Dose.status, func.count()).where(Dose.due_at >= day, Dose.due_at <= now)
                               .group_by(bucket, Dose.status)):
        row = series.setdefault(b, {"hour": iso(b), "confirmed": 0, "missed": 0, "failed": 0, "pending": 0})
        key = {"taken": "confirmed", "late": "confirmed"}.get(st.value, st.value)
        row[key] += n
    return {
        "now": iso(now),
        "devices": {s.value: devices.get(s, 0) for s in DeviceStatus} | {"total": sum(devices.values())},
        "alerts": {"open_by_severity": {s.value: open_by_sev.get(s, 0) for s in Severity}, "open": sum(open_by_sev.values()),
                   "acknowledged": acked, "overdue": overdue},
        "doses_24h": {s.value: doses.get(s, 0) for s in DoseStatus},
        "adherence_24h": round(confirmed / counted * 100, 1) if counted else None,
        "messages_1h": {s.value: msgs.get(s, 0) for s in TelemetryStatus} | {"total": sum(msgs.values())},
        "pending_commands": pending_cmds,
        "dose_series": sorted(series.values(), key=lambda r: r["hour"]),
    }


@router.get("/audit", response_model=Page[dict])
def audit_log(entity_type: str | None = Query(None, max_length=40), p: PageParams = Depends(page_params),
              _: User = Depends(require("audit:read")), db: Session = Depends(get_db)):
    stmt = select(AuditLog).options(joinedload(AuditLog.actor)).order_by(AuditLog.id.desc())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    items, total = paginate(db, stmt, p)
    return Page(items=[{"id": a.id, "ts": iso(a.ts), "actor": a.actor.full_name if a.actor else None, "action": a.action,
                        "entity_type": a.entity_type, "entity_id": a.entity_id, "changes": a.changes,
                        "request_id": a.request_id} for a in items], total=total, page=p.page, page_size=p.page_size)
