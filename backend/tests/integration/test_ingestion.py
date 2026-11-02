"""Ingestion rules: validation, de-duplication, ordering, offline buffers and state changes. [TC codes in names]"""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.models import Alert, AlertStatus, AlertType, Command, CommandStatus, CommandType, Device, DeviceStatus, Dose, \
    DoseStatus, Telemetry, TelemetryStatus
from app.services.escalation import run_pass
from tests.integration.conftest import T0


def alerts(db, device, type_=None, status=None):
    stmt = select(Alert).where(Alert.device_id == device.id)
    if type_:
        stmt = stmt.where(Alert.type == type_)
    if status:
        stmt = stmt.where(Alert.status == status)
    return db.scalars(stmt.execution_options(populate_existing=True)).all()


def test_tc001_heartbeat_updates_device_state(db, make_device, sender):
    d = make_device()
    t = sender(d.serial).heartbeat(T0, battery=88, roll=17)
    db.refresh(d)
    assert t.status == TelemetryStatus.accepted
    assert (d.status, d.battery_pct, d.roll_remaining, d.last_seen_at) == (DeviceStatus.online, 88, 17, T0)


def test_tc002_duplicate_msg_id_is_logged_but_not_applied(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    due = T0
    s("dose_due", {"due_at": due.isoformat()}, at=T0)
    first = s("dose_taken", {"due_at": due.isoformat(), "sachet_id": "S1"}, at=T0 + timedelta(minutes=3), msg_id="dup-0000001")
    second = s("dose_taken", {"due_at": due.isoformat(), "sachet_id": "S2"}, at=T0 + timedelta(minutes=3), msg_id="dup-0000001")
    assert (first.status, second.status) == (TelemetryStatus.accepted, TelemetryStatus.duplicate)
    dose = db.scalars(select(Dose).where(Dose.device_id == d.id)).one()
    assert dose.sachet_id == "S1"  # the repeat did not overwrite anything


def test_tc003_invalid_payload_is_rejected_and_logged(db, make_device, sender):
    d = make_device()
    t = sender(d.serial)("heartbeat", {}, at=T0, raw=b'{"msg_id": "trunc')
    assert t.status == TelemetryStatus.invalid and t.error == "Malformed JSON" and t.raw.startswith('{"msg_id"')
    t2 = sender(d.serial)("heartbeat", {"battery_pct": 150, "roll_remaining": 1, "firmware": "x", "rssi_dbm": -50}, at=T0)
    assert t2.status == TelemetryStatus.invalid and "battery_pct" in t2.error
    db.refresh(d)
    assert d.status == DeviceStatus.never_seen  # invalid messages don't count as a sign of life


def test_tc004_unknown_device_and_topic_mismatch(db, make_device, sender):
    d = make_device()
    unknown = sender("MD-00000").heartbeat(T0)
    assert unknown.status == TelemetryStatus.unknown_device
    spoofed = sender(d.serial).heartbeat(T0, topic_serial="MD-24001")
    assert spoofed.status == TelemetryStatus.invalid and "does not match topic" in spoofed.error


def test_tc005_out_of_order_messages_are_flagged_but_applied(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0, seq=10)
    late = s("dose_due", {"due_at": T0.isoformat()}, at=T0, seq=7)
    assert late.status == TelemetryStatus.accepted and late.out_of_order
    db.refresh(d)
    assert d.last_seq == 10  # the high-water mark never goes backwards


def test_tc033_boot_starts_a_new_sequence(db, make_device, sender):
    """BUG-003 regression: after a power cycle seq restarts at 1; that must not flag every message out of order."""
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0, seq=40)
    boot = s("boot", {"firmware": "2.4.1", "boot_count": 2}, at=T0 + timedelta(minutes=1), seq=1)
    after = s.heartbeat(T0 + timedelta(minutes=6), seq=2)
    assert not boot.out_of_order and not after.out_of_order
    db.refresh(d)
    assert d.last_seq == 2
    # A buffered boot replayed after reconnect is history, not a new power-on.
    s.heartbeat(T0 + timedelta(minutes=11), seq=3)
    replay = s("boot", {"firmware": "2.4.1", "boot_count": 2}, at=T0, seq=1, buffered=True)
    db.refresh(d)
    assert replay.out_of_order and d.last_seq == 3


def test_tc006_buffered_heartbeat_does_not_trigger_clock_drift(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    # A heartbeat recorded 40 min ago, delivered now from the offline buffer.
    s.heartbeat(T0 - timedelta(minutes=40), now=T0, buffered=True, battery=50)
    db.refresh(d)
    assert d.clock_offset_s is None and d.battery_pct is None  # stale snapshot ignored
    assert not alerts(db, d, AlertType.clock_drift)


def test_tc007_live_heartbeat_with_skewed_clock_raises_drift_and_recovers(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0 + timedelta(minutes=25), now=T0)
    [a] = alerts(db, d, AlertType.clock_drift)
    assert a.status == AlertStatus.open and "+25 min" in a.message
    s.heartbeat(T0 + timedelta(minutes=4), now=T0 + timedelta(minutes=4))  # in sync again
    [a] = alerts(db, d, AlertType.clock_drift)
    assert a.status == AlertStatus.resolved and a.auto_resolved


def test_tc008_drift_threshold_boundary(db, make_device, sender):
    d = make_device()
    sender(d.serial).heartbeat(T0 + timedelta(minutes=5), now=T0)  # exactly at threshold: not "more than 5 min"
    assert not alerts(db, d, AlertType.clock_drift)
    sender(d.serial).heartbeat(T0 + timedelta(minutes=5, seconds=1), now=T0, seq=99)
    assert alerts(db, d, AlertType.clock_drift)


def test_tc009_late_confirmation_turns_missed_into_late_and_resolves_alert(db, make_device, sender):
    d = make_device(schedule=("08:00",))
    run_pass(db, T0 + timedelta(minutes=31))  # no confirmation within 30 min -> missed
    db.commit()
    [a] = alerts(db, d, AlertType.missed_dose)
    assert a.status == AlertStatus.open
    # The device was offline; its buffered confirmation arrives 50 min after the dose was taken.
    sender(d.serial)("dose_taken", {"due_at": T0.isoformat(), "sachet_id": "S9"}, at=T0 + timedelta(minutes=10),
                     now=T0 + timedelta(minutes=60), buffered=True)
    dose = db.scalars(select(Dose).where(Dose.device_id == d.id).execution_options(populate_existing=True)).one()
    [a] = alerts(db, d, AlertType.missed_dose)
    assert dose.status == DoseStatus.late and dose.taken_at == T0 + timedelta(minutes=10)
    assert a.status == AlertStatus.resolved and a.auto_resolved and "after reconnecting" in a.resolution


def test_tc010_dispense_failure_raises_alert_per_dose(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    for _ in range(2):  # repeated failure for the same dose -> still one alert
        s("dispense_failed", {"due_at": T0.isoformat(), "reason": "sachet_unreadable"}, at=T0 + timedelta(minutes=2))
    [a] = alerts(db, d, AlertType.dispense_failed)
    dose = db.scalars(select(Dose).where(Dose.device_id == d.id)).one()
    assert dose.status == DoseStatus.failed and dose.failure_reason == "sachet_unreadable"
    assert "unreadable" in a.message


def test_tc011_battery_low_and_recovery_hysteresis(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0, battery=19)
    assert alerts(db, d, AlertType.battery_low, AlertStatus.open)
    s.heartbeat(T0 + timedelta(minutes=5), battery=25)  # above threshold but below +10: stays open (no flapping)
    assert alerts(db, d, AlertType.battery_low, AlertStatus.open)
    s.heartbeat(T0 + timedelta(minutes=10), battery=31)
    assert alerts(db, d, AlertType.battery_low, AlertStatus.resolved)


def test_tc012_roll_low_empty_and_replaced(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0, roll=2)
    s.heartbeat(T0 + timedelta(minutes=5), roll=0)
    assert alerts(db, d, AlertType.roll_low, AlertStatus.open) and alerts(db, d, AlertType.roll_empty, AlertStatus.open)
    s.heartbeat(T0 + timedelta(minutes=10), roll=28)
    assert not [a for a in alerts(db, d) if a.status != AlertStatus.resolved]


def test_tc013_command_ack_completes_command(db, make_device, sender):
    d = make_device()
    c = Command(device_id=d.id, type=CommandType.reboot, status=CommandStatus.sent, created_at=T0)
    db.add(c)
    db.commit()
    sender(d.serial)("command_ack", {"command_id": c.id, "ok": False, "detail": "busy"}, at=T0 + timedelta(minutes=1))
    db.refresh(c)
    assert (c.status, c.result) == (CommandStatus.failed, "busy")
    # An ack for another device's command is ignored.
    other = make_device()
    sender(other.serial)("command_ack", {"command_id": c.id, "ok": True}, at=T0 + timedelta(minutes=2))
    db.refresh(c)
    assert c.status == CommandStatus.failed


def test_tc014_reconnect_resolves_offline_alert(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0)
    run_pass(db, T0 + timedelta(minutes=16))
    db.commit()
    db.refresh(d)
    assert d.status == DeviceStatus.offline and alerts(db, d, AlertType.device_offline, AlertStatus.open)
    s.heartbeat(T0 + timedelta(minutes=20), now=T0 + timedelta(minutes=20))
    db.refresh(d)
    assert d.status == DeviceStatus.online and alerts(db, d, AlertType.device_offline, AlertStatus.resolved)


def test_every_message_is_logged(db, make_device, sender):
    d = make_device()
    s = sender(d.serial)
    s.heartbeat(T0, msg_id="log-000001")
    s.heartbeat(T0, msg_id="log-000001")
    s("x", {}, at=T0, raw=b"nonsense")
    n = db.scalar(select(func.count()).select_from(Telemetry).where(Telemetry.serial == d.serial))
    assert n == 3
