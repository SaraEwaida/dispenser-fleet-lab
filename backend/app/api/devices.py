import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api.common import Page, PageParams, get_device, iso, page_params, paginate
from app.core.clock import get_clock
from app.core.errors import AppError, unprocessable
from app.core.security import require
from app.db.session import get_db
from app.models import (
    Alert, AlertStatus, Client, Command, CommandStatus, CommandType, Device, DeviceStatus, Dose, DoseSchedule,
    DoseStatus, Fault, FaultType, Telemetry, TelemetryStatus, User,
)
from app.services.audit import audit

router = APIRouter(tags=["Devices"])

CONFIRMED = (DoseStatus.taken, DoseStatus.late)
COUNTED = (DoseStatus.taken, DoseStatus.late, DoseStatus.missed, DoseStatus.failed)


def adherence_by_device(db: Session, since) -> dict[int, tuple[int, int]]:
    rows = db.execute(select(Dose.device_id, func.count().filter(Dose.status.in_(CONFIRMED)),
                             func.count().filter(Dose.status.in_(COUNTED)))
                      .where(Dose.due_at >= since).group_by(Dose.device_id)).all()
    return {d: (ok, total) for d, ok, total in rows}


def device_summary(d: Device, open_alerts: int, faults: list[str], adh: tuple[int, int] | None) -> dict:
    ok, total = adh or (0, 0)
    return {
        "serial": d.serial, "status": d.status.value, "firmware": d.firmware, "battery_pct": d.battery_pct,
        "roll_remaining": d.roll_remaining, "roll_capacity": d.roll_capacity, "rssi_dbm": d.rssi_dbm,
        "clock_offset_s": d.clock_offset_s, "last_seen_at": iso(d.last_seen_at),
        "client": {"code": d.client.client_code, "name": d.client.display_name, "care_team": d.client.care_team,
                   "timezone": d.client.timezone},
        "open_alerts": open_alerts, "faults": faults,
        "adherence_24h": round(ok / total * 100, 1) if total else None, "doses_24h": total,
    }


@router.get("/devices", response_model=Page[dict])
def list_devices(
    q: str | None = Query(None, max_length=60), status: DeviceStatus | None = None,
    has_alerts: bool | None = None, has_faults: bool | None = None,
    p: PageParams = Depends(page_params), _: User = Depends(require("devices:read")), db: Session = Depends(get_db),
):
    open_count = (select(func.count()).where(Alert.device_id == Device.id, Alert.status != AlertStatus.resolved)
                  .correlate(Device).scalar_subquery())
    stmt = select(Device).join(Client).options(selectinload(Device.client)).where(Device.is_active)
    if q and q.strip():
        t = f"%{q.strip()}%"
        stmt = stmt.where(or_(Device.serial.ilike(t), Client.client_code.ilike(t), Client.display_name.ilike(t),
                              Client.care_team.ilike(t)))
    if status:
        stmt = stmt.where(Device.status == status)
    if has_alerts is not None:
        stmt = stmt.where(open_count > 0 if has_alerts else open_count == 0)
    if has_faults is not None:
        exists = select(Fault.id).where(Fault.device_id == Device.id).exists()
        stmt = stmt.where(exists if has_faults else ~exists)
    stmt = stmt.order_by(open_count.desc(), Device.serial)
    items, total = paginate(db, stmt, p)
    ids = [d.id for d in items]
    counts = dict(db.execute(select(Alert.device_id, func.count()).where(Alert.device_id.in_(ids), Alert.status != AlertStatus.resolved)
                             .group_by(Alert.device_id)).all())
    faults: dict[int, list[str]] = {}
    for dev_id, f in db.execute(select(Fault.device_id, Fault.type).where(Fault.device_id.in_(ids))):
        faults.setdefault(dev_id, []).append(f.value)
    adh = adherence_by_device(db, get_clock().now() - timedelta(hours=24))
    return Page(items=[device_summary(d, counts.get(d.id, 0), faults.get(d.id, []), adh.get(d.id)) for d in items],
                total=total, page=p.page, page_size=p.page_size)


@router.get("/devices/{serial}")
def device_detail(serial: str, _: User = Depends(require("devices:read")), db: Session = Depends(get_db)):
    d = get_device(db, serial)
    now = get_clock().now()
    tz = ZoneInfo(d.client.timezone)
    open_alerts = db.scalars(select(Alert).where(Alert.device_id == d.id, Alert.status != AlertStatus.resolved)
                             .order_by(Alert.created_at.desc())).all()
    faults = [f.value for f in db.scalars(select(Fault.type).where(Fault.device_id == d.id))]
    doses = db.scalars(select(Dose).where(Dose.device_id == d.id, Dose.due_at >= now - timedelta(hours=48))
                       .order_by(Dose.due_at.desc())).all()
    commands = db.scalars(select(Command).where(Command.device_id == d.id).order_by(Command.id.desc()).limit(15)).all()
    adh = adherence_by_device(db, now - timedelta(hours=24)).get(d.id)
    return {
        **device_summary(d, len(open_alerts), faults, adh),
        "schedule": [s.time_of_day for s in d.schedule], "local_time": now.astimezone(tz).strftime("%H:%M"),
        "alerts": [alert_brief(a) for a in open_alerts],
        "doses": [{"id": x.id, "due_at": iso(x.due_at), "due_local": x.due_at.astimezone(tz).strftime("%a %H:%M"),
                   "status": x.status.value, "taken_at": iso(x.taken_at), "confirmed_at": iso(x.confirmed_at),
                   "failure_reason": x.failure_reason} for x in doses],
        "commands": [command_out(c) for c in commands],
    }


def alert_brief(a: Alert) -> dict:
    return {"id": a.id, "code": a.code, "type": a.type.value, "severity": a.severity.value, "status": a.status.value,
            "message": a.message, "created_at": iso(a.created_at), "ack_due_at": iso(a.ack_due_at)}


def command_out(c: Command) -> dict:
    return {"id": c.id, "type": c.type.value, "status": c.status.value, "created_at": iso(c.created_at),
            "sent_at": iso(c.sent_at), "completed_at": iso(c.completed_at), "result": c.result}


@router.get("/devices/{serial}/messages", response_model=Page[dict])
def device_messages(serial: str, p: PageParams = Depends(page_params), _: User = Depends(require("telemetry:read")),
                    db: Session = Depends(get_db)):
    d = get_device(db, serial)
    from app.api.telemetry import telemetry_out
    stmt = select(Telemetry).where(or_(Telemetry.device_id == d.id, Telemetry.serial == d.serial)).order_by(Telemetry.id.desc())
    items, total = paginate(db, stmt, p)
    return Page(items=[telemetry_out(t) for t in items], total=total, page=p.page, page_size=p.page_size)


class CommandIn(BaseModel):
    type: CommandType


@router.post("/devices/{serial}/commands", status_code=201)
def send_command(serial: str, body: CommandIn, user: User = Depends(require("devices:command")), db: Session = Depends(get_db)):
    d = get_device(db, serial)
    pending = db.scalar(select(Command.id).where(Command.device_id == d.id, Command.type == body.type,
                                                 Command.status.in_([CommandStatus.queued, CommandStatus.sent])))
    if pending:
        raise AppError(409, "COMMAND_PENDING", f"A {body.type.value} command is already waiting for this device.")
    c = Command(device_id=d.id, type=body.type, created_by=user.id, created_at=get_clock().now())
    db.add(c)
    db.flush()
    audit(db, user, "command", "device", d.serial, {"type": body.type.value})
    db.commit()
    return {**command_out(c), "note": None if d.status == DeviceStatus.online else
            "Device is not online. The command is queued and will be delivered when it reconnects (expires after 60 sim-min)."}


class ScheduleIn(BaseModel):
    times: list[str] = Field(min_length=1, max_length=6)

    @field_validator("times")
    @classmethod
    def valid_times(cls, v: list[str]) -> list[str]:
        for t in v:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                raise ValueError(f"'{t}' is not a valid time (HH:MM, 24-hour).")
        if len(set(v)) != len(v):
            raise ValueError("Times must be unique.")
        return sorted(v)


@router.put("/devices/{serial}/schedule")
def set_schedule(serial: str, body: ScheduleIn, user: User = Depends(require("devices:schedule")), db: Session = Depends(get_db)):
    d = get_device(db, serial, lock=True)
    old = [s.time_of_day for s in d.schedule]
    db.execute(delete(DoseSchedule).where(DoseSchedule.device_id == d.id))
    db.add_all(DoseSchedule(device_id=d.id, time_of_day=t) for t in body.times)
    # Expectations change now: future doses come from the new schedule; past slots are unaffected.
    db.add(Command(device_id=d.id, type=CommandType.sync_schedule, created_by=user.id, created_at=get_clock().now()))
    audit(db, user, "update", "schedule", d.serial, {"times": {"from": old, "to": body.times}})
    db.commit()
    return {"serial": d.serial, "schedule": body.times, "note": "A sync_schedule command was queued for the device."}


# ---------------- Fault Lab ----------------
FAULT_INFO = {
    FaultType.offline: "Device loses connectivity. Events are buffered on the device and delivered when it reconnects.",
    FaultType.duplicate_messages: "Every message is published twice with the same msg_id (e.g. a retry after a lost ACK).",
    FaultType.corrupt_payload: "About a third of messages are malformed or miss required fields.",
    FaultType.clock_drift: "Device clock jumps 25 min ahead. Remote resync is rejected while the fault is active.",
    FaultType.no_response: "The client never presses the button when reminded.",
    FaultType.read_error: "Sachet print can't be read; the dispenser refuses to dispense.",
    FaultType.battery_drain: "Backup battery drains quickly, as if the device were unplugged.",
}


@router.get("/faults")
def list_faults(_: User = Depends(require("devices:read")), db: Session = Depends(get_db)):
    rows = db.execute(select(Fault, Device.serial).join(Device, Device.id == Fault.device_id).order_by(Fault.enabled_at.desc())).all()
    return {"catalog": [{"type": k.value, "description": v} for k, v in FAULT_INFO.items()],
            "active": [{"serial": s, "type": f.type.value, "enabled_at": iso(f.enabled_at)} for f, s in rows]}


class FaultIn(BaseModel):
    type: FaultType


@router.post("/devices/{serial}/faults", status_code=201)
def enable_fault(serial: str, body: FaultIn, user: User = Depends(require("faults:manage")), db: Session = Depends(get_db)):
    d = get_device(db, serial)
    if db.scalar(select(Fault.id).where(Fault.device_id == d.id, Fault.type == body.type)):
        raise AppError(409, "FAULT_ACTIVE", f"{body.type.value} is already active on {serial}.")
    db.add(Fault(device_id=d.id, type=body.type, enabled_by=user.id))
    audit(db, user, "fault_enabled", "device", serial, {"fault": body.type.value})
    db.commit()
    return {"serial": serial, "type": body.type.value, "description": FAULT_INFO[body.type]}


@router.delete("/devices/{serial}/faults/{fault}", status_code=204)
def disable_fault(serial: str, fault: FaultType, user: User = Depends(require("faults:manage")), db: Session = Depends(get_db)):
    d = get_device(db, serial)
    res = db.execute(delete(Fault).where(Fault.device_id == d.id, Fault.type == fault))
    if not res.rowcount:
        raise AppError(404, "NOT_FOUND", f"{fault.value} is not active on {serial}.")
    audit(db, user, "fault_disabled", "device", serial, {"fault": fault.value})
    db.commit()


@router.delete("/faults", status_code=200)
def clear_all_faults(user: User = Depends(require("faults:manage")), db: Session = Depends(get_db)):
    n = db.execute(delete(Fault)).rowcount
    audit(db, user, "fault_disabled", "fleet", None, {"cleared": n})
    db.commit()
    return {"cleared": n}
