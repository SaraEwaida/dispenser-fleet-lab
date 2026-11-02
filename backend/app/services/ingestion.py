"""Process one device message: validate, de-duplicate, order, store, and apply its effect.

Design rules (each is covered by tests):
- Every received message is logged in `telemetry`, including rejected ones.
- A msg_id is applied at most once; repeats are logged as duplicates and ignored.
- Messages may arrive late or out of order (offline buffer). Effects are idempotent and keyed by the dose's
  due time, so order does not change the outcome.
- Clock drift is measured only on live (non-buffered) heartbeats; a buffered heartbeat is old by design.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.protocol import Boot, CommandAck, DispenseFailed, DoseDue, DoseTaken, Heartbeat, parse_message, serial_from_topic
from app.models import (
    Alert, AlertType, Command, CommandStatus, Device, DeviceStatus, Dose, DoseStatus, Telemetry, TelemetryStatus,
)
from app.services.alerts import auto_resolve, raise_alert, resolve_condition


def _get_or_create_dose(db: Session, device: Device, due_at: datetime) -> Dose:
    db.execute(insert(Dose).values(device_id=device.id, due_at=due_at, status=DoseStatus.pending)
               .on_conflict_do_nothing(constraint="uq_dose_per_slot"))
    return db.scalars(select(Dose).where(Dose.device_id == device.id, Dose.due_at == due_at).with_for_update()).one()


def process_raw(db: Session, topic: str, raw: bytes, now: datetime) -> Telemetry:
    """Entry point used by the MQTT subscriber. Commits nothing; the caller commits."""
    settings = get_settings()
    topic_serial = serial_from_topic(topic)
    msg, error = parse_message(raw)
    if msg is None:
        t = Telemetry(serial=topic_serial, received_at=now, status=TelemetryStatus.invalid, error=error,
                      raw=raw[:2000].decode("utf-8", errors="replace"))
        db.add(t)
        return t
    payload = msg.model_dump(mode="json")
    if topic_serial and msg.serial != topic_serial:
        t = Telemetry(msg_id=msg.msg_id, serial=topic_serial, type=msg.type, seq=msg.seq, device_ts=msg.ts,
                      received_at=now, status=TelemetryStatus.invalid, payload=payload,
                      error=f"Serial in payload ({msg.serial}) does not match topic ({topic_serial})")
        db.add(t)
        return t

    device = db.scalars(select(Device).where(Device.serial == msg.serial).with_for_update()).first()
    base = dict(msg_id=msg.msg_id, serial=msg.serial, type=msg.type, seq=msg.seq, device_ts=msg.ts, received_at=now,
                payload=payload, buffered=msg.buffered)
    if device is None or not device.is_active:
        t = Telemetry(**base, status=TelemetryStatus.unknown_device, error="Serial is not registered to an active device")
        db.add(t)
        return t

    if db.scalar(select(Telemetry.id).where(Telemetry.msg_id == msg.msg_id, Telemetry.status == TelemetryStatus.accepted)):
        t = Telemetry(**base, device_id=device.id, status=TelemetryStatus.duplicate, error="msg_id already processed")
        db.add(t)
        return t

    # The sequence counter restarts at 1 on every power-on, so a live boot message opens a new sequence (BUG-003).
    new_sequence = isinstance(msg, Boot) and not msg.buffered
    out_of_order = not new_sequence and msg.seq <= device.last_seq
    t = Telemetry(**base, device_id=device.id, status=TelemetryStatus.accepted, out_of_order=out_of_order)
    db.add(t)
    db.flush()

    # Any accepted message proves the device is connected now.
    device.last_seen_at = now
    device.last_seq = msg.seq if new_sequence else max(device.last_seq, msg.seq)
    if device.status != DeviceStatus.online:
        device.status = DeviceStatus.online
        resolve_condition(db, device.id, AlertType.device_offline, now, "Device reconnected; messages received again.")

    if isinstance(msg, Heartbeat):
        _apply_heartbeat(db, device, msg, now, settings)
    elif isinstance(msg, DoseDue):
        _get_or_create_dose(db, device, msg.data.due_at)
    elif isinstance(msg, DoseTaken):
        _apply_dose_taken(db, device, msg, now)
    elif isinstance(msg, DispenseFailed):
        _apply_dispense_failed(db, device, msg, now)
    elif isinstance(msg, CommandAck):
        _apply_command_ack(db, device, msg, now)
    elif isinstance(msg, Boot):
        device.firmware = msg.data.firmware
    return t


def _apply_heartbeat(db: Session, device: Device, msg: Heartbeat, now: datetime, s) -> None:
    if msg.buffered:
        return  # stale snapshot from the offline buffer: do not overwrite current state or measure drift
    d = msg.data
    device.battery_pct, device.roll_remaining, device.firmware, device.rssi_dbm = (
        d.battery_pct, min(d.roll_remaining, device.roll_capacity), d.firmware, d.rssi_dbm)
    device.clock_offset_s = int((msg.ts - now).total_seconds())

    if abs(device.clock_offset_s) > s.clock_drift_threshold_minutes * 60:
        raise_alert(db, device, AlertType.clock_drift,
                    f"Device clock is {device.clock_offset_s // 60:+d} min off. Dose times may be wrong.", now)
    elif abs(device.clock_offset_s) < 60:
        resolve_condition(db, device.id, AlertType.clock_drift, now, "Clock back in sync (offset < 1 min).")

    if d.battery_pct < s.battery_low_pct:
        raise_alert(db, device, AlertType.battery_low, f"Backup battery at {d.battery_pct}%.", now)
    elif d.battery_pct >= s.battery_low_pct + 10:
        resolve_condition(db, device.id, AlertType.battery_low, now, f"Battery recovered to {d.battery_pct}%.")

    if d.roll_remaining == 0:
        raise_alert(db, device, AlertType.roll_empty, "Medication roll is empty. Next doses cannot be dispensed.", now)
    elif d.roll_remaining <= s.roll_low_sachets:
        raise_alert(db, device, AlertType.roll_low, f"Only {d.roll_remaining} sachet(s) left on the roll.", now)
    else:
        resolve_condition(db, device.id, AlertType.roll_low, now, f"Roll replaced ({d.roll_remaining} sachets).")
        resolve_condition(db, device.id, AlertType.roll_empty, now, f"Roll replaced ({d.roll_remaining} sachets).")


def _apply_dose_taken(db: Session, device: Device, msg: DoseTaken, now: datetime) -> None:
    dose = _get_or_create_dose(db, device, msg.data.due_at)
    if dose.status in (DoseStatus.taken, DoseStatus.late):
        return
    was_missed = dose.status == DoseStatus.missed
    dose.status = DoseStatus.late if was_missed else DoseStatus.taken
    dose.taken_at, dose.confirmed_at, dose.sachet_id = msg.ts, now, msg.data.sachet_id
    dose.failure_reason = None
    if was_missed:
        alert = db.scalars(select(Alert).where(Alert.dose_id == dose.id, Alert.type == AlertType.missed_dose)).first()
        delay = "after reconnecting" if msg.buffered else "late"
        auto_resolve(db, alert, now, f"Device confirmed the dose {delay}: taken at {msg.ts:%H:%M} (device time).")


def _apply_dispense_failed(db: Session, device: Device, msg: DispenseFailed, now: datetime) -> None:
    dose = _get_or_create_dose(db, device, msg.data.due_at)
    if dose.status in (DoseStatus.taken, DoseStatus.late):
        return
    dose.status, dose.failure_reason = DoseStatus.failed, msg.data.reason
    text = {"sachet_unreadable": "Sachet print unreadable; dose not dispensed.",
            "roll_empty": "Roll empty; dose not dispensed.", "jam": "Dispenser jammed; dose not dispensed."}[msg.data.reason]
    raise_alert(db, device, AlertType.dispense_failed, f"{text} Due {dose.due_at:%H:%M}.", now, dose_id=dose.id)


def _apply_command_ack(db: Session, device: Device, msg: CommandAck, now: datetime) -> None:
    cmd = db.get(Command, msg.data.command_id)
    if cmd is None or cmd.device_id != device.id or cmd.status not in (CommandStatus.sent, CommandStatus.queued):
        return
    cmd.status = CommandStatus.acked if msg.data.ok else CommandStatus.failed
    cmd.completed_at, cmd.result = now, msg.data.detail
