"""Escalation engine: runs every few real seconds and turns *absence* of messages into alerts.

The cloud never relies on a device to report its own failure: a device that is offline cannot say so, and a
client who ignores the reminder produces no message at all. So the engine works from the schedule:
  1. materialise expected doses from each device's schedule (in the client's timezone);
  2. devices silent longer than the offline threshold -> offline + alert;
  3. pending doses with no confirmation after the grace period -> missed + alert;
  4. commands that could not be delivered in time -> expired.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.models import (
    AlertType, Client, Command, CommandStatus, Device, DeviceStatus, Dose, DoseStatus,
)
from app.services.alerts import raise_alert


def due_times(schedule: list[str], tz: str, start: datetime, end: datetime) -> list[datetime]:
    """All scheduled times in (start, end], as UTC datetimes. DST-safe via zoneinfo."""
    zone = ZoneInfo(tz)
    out = []
    day: date = start.astimezone(zone).date() - timedelta(days=1)
    last = end.astimezone(zone).date()
    while day <= last:
        for hhmm in schedule:
            h, m = map(int, hhmm.split(":"))
            local = datetime.combine(day, time(h, m), tzinfo=zone)
            utc = local.astimezone(ZoneInfo("UTC"))
            if start < utc <= end:
                out.append(utc)
        day += timedelta(days=1)
    return sorted(out)


def run_pass(db: Session, now: datetime) -> dict:
    s = get_settings()
    stats = {"doses_created": 0, "missed": 0, "offline": 0, "commands_expired": 0}
    devices = db.scalars(select(Device).where(Device.is_active).options(selectinload(Device.schedule))).all()
    clients = {c.id: c for c in db.scalars(select(Client))}

    # 1. Expected doses: look back one day (bounded by commissioning) so a restart never loses a slot.
    for d in devices:
        start = max(d.commissioned_at, now - timedelta(days=1))
        for due in due_times([x.time_of_day for x in d.schedule], clients[d.client_id].timezone, start, now):
            res = db.execute(insert(Dose).values(device_id=d.id, due_at=due, status=DoseStatus.pending)
                             .on_conflict_do_nothing(constraint="uq_dose_per_slot"))
            stats["doses_created"] += res.rowcount or 0

    # 2. Offline devices first, so a missed-dose alert raised in the same pass knows the device is offline.
    silent_since = now - timedelta(minutes=s.offline_after_minutes)
    for d in devices:
        if d.status == DeviceStatus.online and d.last_seen_at and d.last_seen_at < silent_since:
            d.status = DeviceStatus.offline
            mins = int((now - d.last_seen_at).total_seconds() // 60)
            raise_alert(db, d, AlertType.device_offline, f"No messages for {mins} min (heartbeat every "
                        f"{s.heartbeat_interval_minutes} min).", now)
            stats["offline"] += 1

    # 3. Missed doses.
    deadline = now - timedelta(minutes=s.dose_grace_minutes)
    by_id = {d.id: d for d in devices}
    for dose in db.scalars(select(Dose).where(Dose.status == DoseStatus.pending, Dose.due_at <= deadline)
                           .with_for_update(skip_locked=True)):
        device = by_id.get(dose.device_id)
        if device is None:
            continue
        dose.status = DoseStatus.missed
        why = " Device is offline, so the dose may have been taken without confirmation." \
            if device.status == DeviceStatus.offline else ""
        raise_alert(db, device, AlertType.missed_dose,
                    f"No confirmation for the {dose.due_at.astimezone(ZoneInfo(clients[device.client_id].timezone)):%H:%M} "
                    f"dose ({s.dose_grace_minutes} min after due time).{why}", now, dose_id=dose.id)
        stats["missed"] += 1

    # 4. Expire undeliverable commands.
    expiry = now - timedelta(minutes=s.command_expiry_minutes)
    for c in db.scalars(select(Command).where(Command.status.in_([CommandStatus.queued, CommandStatus.sent]),
                                              Command.created_at <= expiry)):
        c.status, c.completed_at, c.result = CommandStatus.expired, now, "Device did not acknowledge in time."
        stats["commands_expired"] += 1
    return stats
