from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, AlertStatus, AlertType, Device, Severity

# Acknowledgement SLA per severity, in simulated minutes.
ACK_SLA_MINUTES = {Severity.critical: 5, Severity.high: 15, Severity.medium: 60, Severity.low: 240}

SEVERITY = {
    AlertType.missed_dose: Severity.high,
    AlertType.dispense_failed: Severity.high,
    AlertType.roll_empty: Severity.high,
    AlertType.device_offline: Severity.medium,
    AlertType.roll_low: Severity.medium,
    AlertType.clock_drift: Severity.medium,
    AlertType.battery_low: Severity.low,
}


def open_condition_alert(db: Session, device_id: int, type_: AlertType) -> Alert | None:
    return db.scalars(select(Alert).where(Alert.device_id == device_id, Alert.type == type_, Alert.dose_id.is_(None),
                                          Alert.status != AlertStatus.resolved)).first()


def raise_alert(db: Session, device: Device, type_: AlertType, message: str, now: datetime,
                dose_id: int | None = None) -> Alert | None:
    """Create an alert unless an equivalent one is already open. Returns the new alert, or None."""
    if dose_id is not None:
        exists = db.scalar(select(Alert.id).where(Alert.dose_id == dose_id, Alert.type == type_))
    else:
        exists = open_condition_alert(db, device.id, type_)
    if exists:
        return None
    severity = SEVERITY[type_]
    alert = Alert(device_id=device.id, dose_id=dose_id, type=type_, severity=severity, message=message[:300],
                  created_at=now, ack_due_at=now + timedelta(minutes=ACK_SLA_MINUTES[severity]))
    db.add(alert)
    db.flush()
    return alert


def auto_resolve(db: Session, alert: Alert | None, now: datetime, resolution: str) -> bool:
    if alert is None or alert.status == AlertStatus.resolved:
        return False
    alert.status, alert.resolved_at, alert.auto_resolved, alert.resolution = AlertStatus.resolved, now, True, resolution
    return True


def resolve_condition(db: Session, device_id: int, type_: AlertType, now: datetime, resolution: str) -> bool:
    return auto_resolve(db, open_condition_alert(db, device_id, type_), now, resolution)
