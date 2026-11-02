"""Escalation engine: schedule-driven expectations and timing boundaries."""

from datetime import timedelta

from sqlalchemy import select

from app.models import Alert, AlertType, Command, CommandStatus, CommandType, DeviceStatus, Dose, DoseStatus
from app.services.escalation import run_pass
from tests.integration.conftest import T0


def doses(db, d):
    return db.scalars(select(Dose).where(Dose.device_id == d.id).order_by(Dose.due_at)
                      .execution_options(populate_existing=True)).all()


def test_tc015_doses_are_expected_from_schedule_even_without_messages(db, make_device):
    d = make_device(schedule=("08:00", "20:00"))  # commissioned 06:00 local
    run_pass(db, T0 + timedelta(minutes=1))
    db.commit()
    [dose] = doses(db, d)
    assert dose.due_at == T0 and dose.status == DoseStatus.pending


def test_tc016_missed_dose_grace_boundary(db, make_device):
    d = make_device(schedule=("08:00",))
    run_pass(db, T0 + timedelta(minutes=29, seconds=59))
    db.commit()
    assert doses(db, d)[0].status == DoseStatus.pending
    run_pass(db, T0 + timedelta(minutes=30))
    db.commit()
    assert doses(db, d)[0].status == DoseStatus.missed
    [a] = db.scalars(select(Alert).where(Alert.device_id == d.id)).all()
    assert a.type == AlertType.missed_dose and a.severity.value == "high"
    assert a.ack_due_at == a.created_at + timedelta(minutes=15)


def test_tc017_engine_is_idempotent(db, make_device):
    d = make_device(schedule=("08:00",))
    for _ in range(3):
        run_pass(db, T0 + timedelta(minutes=45))
        db.commit()
    assert len(doses(db, d)) == 1
    assert len(db.scalars(select(Alert).where(Alert.device_id == d.id)).all()) == 1


def test_tc018_confirmed_dose_is_never_escalated(db, make_device, sender):
    d = make_device(schedule=("08:00",))
    sender(d.serial)("dose_taken", {"due_at": T0.isoformat(), "sachet_id": "S"}, at=T0 + timedelta(minutes=5))
    run_pass(db, T0 + timedelta(hours=2))
    db.commit()
    assert doses(db, d)[0].status == DoseStatus.taken
    assert not db.scalars(select(Alert).where(Alert.device_id == d.id, Alert.type == AlertType.missed_dose)).all()


def test_tc019_offline_threshold_boundary(db, make_device, sender):
    d = make_device()
    sender(d.serial).heartbeat(T0)
    run_pass(db, T0 + timedelta(minutes=15))  # exactly 15 min silent: not yet offline
    db.commit()
    db.refresh(d)
    assert d.status == DeviceStatus.online
    run_pass(db, T0 + timedelta(minutes=15, seconds=1))
    db.commit()
    db.refresh(d)
    assert d.status == DeviceStatus.offline


def test_tc020_missed_alert_mentions_offline_device(db, make_device, sender):
    """Regression for BUG-002: offline detection must run before missed-dose escalation in the same pass."""
    d = make_device(schedule=("08:00",))
    sender(d.serial).heartbeat(T0 - timedelta(minutes=30), now=T0 - timedelta(minutes=30))
    run_pass(db, T0 + timedelta(minutes=31))
    db.commit()
    missed = db.scalars(select(Alert).where(Alert.device_id == d.id, Alert.type == AlertType.missed_dose)).one()
    assert "offline" in missed.message


def test_tc021_no_doses_before_commissioning(db, make_device):
    d = make_device(schedule=("08:00",), commissioned=T0 + timedelta(minutes=1))
    run_pass(db, T0 + timedelta(hours=3))
    db.commit()
    assert doses(db, d) == []


def test_tc022_schedule_in_other_timezone(db, make_device):
    d = make_device(schedule=("08:00",), tz="Asia/Jerusalem", commissioned=T0 - timedelta(hours=6))
    run_pass(db, T0)  # 08:00 Jerusalem = 06:00 UTC (UTC+2 in November)
    db.commit()
    assert doses(db, d)[0].due_at == T0 - timedelta(hours=1)


def test_tc023_undelivered_command_expires(db, make_device):
    d = make_device()
    c = Command(device_id=d.id, type=CommandType.resync_clock, created_at=T0)
    db.add(c)
    db.commit()
    run_pass(db, T0 + timedelta(minutes=59))
    db.commit()
    db.refresh(c)
    assert c.status == CommandStatus.queued
    run_pass(db, T0 + timedelta(minutes=60))
    db.commit()
    db.refresh(c)
    assert c.status == CommandStatus.expired
