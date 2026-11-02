"""Database models. Device-domain timestamps (doses, telemetry, alerts, commands) are in *simulated* time;
tickets and audit entries use real time."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Sequence, SmallInteger,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Role(StrEnum):
    care_coordinator = "care_coordinator"
    support_engineer = "support_engineer"
    qa_engineer = "qa_engineer"


class DeviceStatus(StrEnum):
    never_seen = "never_seen"
    online = "online"
    offline = "offline"


class DoseStatus(StrEnum):
    pending = "pending"
    taken = "taken"
    late = "late"        # confirmed after it had already been escalated as missed
    missed = "missed"
    failed = "failed"    # dispense failed (unreadable sachet / empty roll)


class AlertType(StrEnum):
    missed_dose = "missed_dose"
    dispense_failed = "dispense_failed"
    device_offline = "device_offline"
    battery_low = "battery_low"
    roll_low = "roll_low"
    roll_empty = "roll_empty"
    clock_drift = "clock_drift"


class AlertStatus(StrEnum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class Severity(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class TelemetryStatus(StrEnum):
    accepted = "accepted"
    duplicate = "duplicate"
    invalid = "invalid"
    unknown_device = "unknown_device"


class CommandType(StrEnum):
    resync_clock = "resync_clock"
    reboot = "reboot"
    sync_schedule = "sync_schedule"
    replace_roll = "replace_roll"   # simulates a caregiver visit that loads a new medication roll


class CommandStatus(StrEnum):
    queued = "queued"
    sent = "sent"
    acked = "acked"
    failed = "failed"
    expired = "expired"


class FaultType(StrEnum):
    offline = "offline"
    duplicate_messages = "duplicate_messages"
    corrupt_payload = "corrupt_payload"
    clock_drift = "clock_drift"
    no_response = "no_response"
    read_error = "read_error"
    battery_drain = "battery_drain"


class TicketStatus(StrEnum):
    open = "open"
    investigating = "investigating"
    escalated = "escalated"
    resolved = "resolved"


class Priority(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


def enum_col(cls, name):
    return SAEnum(cls, native_enum=False, create_constraint=True, length=30, name=name,
                  values_callable=lambda e: [m.value for m in e], validate_strings=True)


def ts(nullable=False, default=False):
    kw = {"server_default": func.now()} if default else {}
    return mapped_column(DateTime(timezone=True), nullable=nullable, **kw)


client_code_seq = Sequence("client_code_seq", start=1001, metadata=Base.metadata)
alert_code_seq = Sequence("alert_code_seq", start=1001, metadata=Base.metadata)
ticket_code_seq = Sequence("ticket_code_seq", start=1001, metadata=Base.metadata)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[Role] = mapped_column(enum_col(Role, "user_role"))
    password_hash: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = ts(default=True)


class Client(Base):
    """Fictional care recipient. Only a display name and care team are stored."""
    __tablename__ = "clients"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    client_code: Mapped[str] = mapped_column(String(12), unique=True, server_default=text("'C-' || nextval('client_code_seq')"))
    display_name: Mapped[str] = mapped_column(String(80))
    care_team: Mapped[str] = mapped_column(String(60))
    timezone: Mapped[str] = mapped_column(String(40), server_default="Europe/Amsterdam")
    created_at: Mapped[datetime] = ts(default=True)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    serial: Mapped[str] = mapped_column(String(20), unique=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), unique=True)
    firmware: Mapped[str] = mapped_column(String(20))
    status: Mapped[DeviceStatus] = mapped_column(enum_col(DeviceStatus, "device_status"), server_default="never_seen")
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    roll_remaining: Mapped[int | None] = mapped_column(SmallInteger)
    roll_capacity: Mapped[int] = mapped_column(SmallInteger, server_default="28")
    rssi_dbm: Mapped[int | None] = mapped_column(SmallInteger)
    clock_offset_s: Mapped[int | None] = mapped_column(Integer)   # device clock minus cloud clock
    last_seen_at: Mapped[datetime | None] = ts(nullable=True)      # sim time of last message received
    last_seq: Mapped[int] = mapped_column(Integer, server_default="0")
    commissioned_at: Mapped[datetime] = ts()                       # sim time from which doses are expected
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    client: Mapped[Client] = relationship()
    schedule: Mapped[list["DoseSchedule"]] = relationship(order_by="DoseSchedule.time_of_day", cascade="all, delete-orphan")
    __table_args__ = (
        CheckConstraint("battery_pct IS NULL OR battery_pct BETWEEN 0 AND 100", name="battery_range"),
        CheckConstraint("roll_remaining IS NULL OR roll_remaining BETWEEN 0 AND roll_capacity", name="roll_range"),
    )


class DoseSchedule(Base):
    __tablename__ = "dose_schedules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    time_of_day: Mapped[str] = mapped_column(String(5))   # "08:00", in the client's timezone
    __table_args__ = (UniqueConstraint("device_id", "time_of_day", name="uq_schedule_time"),
                      CheckConstraint(r"time_of_day ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'", name="time_format"))


class Dose(Base):
    __tablename__ = "doses"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    due_at: Mapped[datetime] = ts()
    status: Mapped[DoseStatus] = mapped_column(enum_col(DoseStatus, "dose_status"), server_default="pending")
    taken_at: Mapped[datetime | None] = ts(nullable=True)          # device-reported time of the button press
    confirmed_at: Mapped[datetime | None] = ts(nullable=True)      # sim time the cloud received the confirmation
    sachet_id: Mapped[str | None] = mapped_column(String(40))
    failure_reason: Mapped[str | None] = mapped_column(String(60))
    __table_args__ = (UniqueConstraint("device_id", "due_at", name="uq_dose_per_slot"),
                      Index("ix_doses_status_due", "status", "due_at"))


class Telemetry(Base):
    """Every MQTT message the cloud received, including rejected ones (the message log)."""
    __tablename__ = "telemetry"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    msg_id: Mapped[str | None] = mapped_column(String(64), index=True)
    serial: Mapped[str | None] = mapped_column(String(40), index=True)
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    type: Mapped[str | None] = mapped_column(String(30))
    seq: Mapped[int | None] = mapped_column(Integer)
    device_ts: Mapped[datetime | None] = ts(nullable=True)
    received_at: Mapped[datetime] = ts()                           # sim time
    status: Mapped[TelemetryStatus] = mapped_column(enum_col(TelemetryStatus, "telemetry_status"))
    out_of_order: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    buffered: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    error: Mapped[str | None] = mapped_column(String(300))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    raw: Mapped[str | None] = mapped_column(Text)                  # only kept for invalid messages
    __table_args__ = (
        Index("uq_telemetry_accepted_msg", "msg_id", unique=True, postgresql_where=text("status = 'accepted'")),
        Index("ix_telemetry_received", "received_at"),
    )


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, server_default=text("'AL-' || nextval('alert_code_seq')"))
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    dose_id: Mapped[int | None] = mapped_column(ForeignKey("doses.id", ondelete="SET NULL"))
    type: Mapped[AlertType] = mapped_column(enum_col(AlertType, "alert_type"))
    severity: Mapped[Severity] = mapped_column(enum_col(Severity, "alert_severity"))
    status: Mapped[AlertStatus] = mapped_column(enum_col(AlertStatus, "alert_status"), server_default="open")
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = ts()                            # sim time
    ack_due_at: Mapped[datetime] = ts()                            # sim time: SLA for acknowledgement
    acknowledged_at: Mapped[datetime | None] = ts(nullable=True)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = ts(nullable=True)
    resolved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    auto_resolved: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    resolution: Mapped[str | None] = mapped_column(String(500))

    device: Mapped[Device] = relationship()
    __table_args__ = (
        # One open condition alert per device and type; missed-dose alerts are unique per dose instead.
        Index("uq_open_condition_alert", "device_id", "type", unique=True,
              postgresql_where=text("status <> 'resolved' AND dose_id IS NULL")),
        Index("uq_alert_per_dose", "dose_id", "type", unique=True, postgresql_where=text("dose_id IS NOT NULL")),
        CheckConstraint("status <> 'resolved' OR resolution IS NOT NULL", name="resolution_required"),
    )


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    type: Mapped[CommandType] = mapped_column(enum_col(CommandType, "command_type"))
    status: Mapped[CommandStatus] = mapped_column(enum_col(CommandStatus, "command_status"), server_default="queued")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts()                            # sim time
    sent_at: Mapped[datetime | None] = ts(nullable=True)
    completed_at: Mapped[datetime | None] = ts(nullable=True)
    result: Mapped[str | None] = mapped_column(String(200))


class Fault(Base):
    __tablename__ = "faults"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    type: Mapped[FaultType] = mapped_column(enum_col(FaultType, "fault_type"))
    enabled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    enabled_at: Mapped[datetime] = ts(default=True)                # real time
    __table_args__ = (UniqueConstraint("device_id", "type", name="uq_fault_per_device"),)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, server_default=text("'SUP-' || nextval('ticket_code_seq')"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    subject: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    reporter: Mapped[str] = mapped_column(String(120))
    priority: Mapped[Priority] = mapped_column(enum_col(Priority, "ticket_priority"), server_default="medium")
    status: Mapped[TicketStatus] = mapped_column(enum_col(TicketStatus, "ticket_status"), server_default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = ts(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    device: Mapped[Device | None] = relationship()
    notes: Mapped[list["TicketNote"]] = relationship(order_by="TicketNote.created_at", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("status <> 'resolved' OR resolution IS NOT NULL", name="resolution_required"),
                      CheckConstraint("length(trim(subject)) >= 5", name="subject_min"))


class TicketNote(Base):
    __tablename__ = "ticket_notes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = ts(default=True)
    author: Mapped[User] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ts: Mapped[datetime] = ts(default=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[str | None] = mapped_column(String(40))
    changes: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    actor: Mapped[User | None] = relationship()
