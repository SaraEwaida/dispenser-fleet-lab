"""Device <-> cloud protocol (MQTT, JSON payloads).

Topics
  fleet/v1/devices/{serial}/events     device -> cloud   (QoS 1)
  fleet/v1/devices/{serial}/commands   cloud  -> device  (QoS 1)

Every event carries a unique msg_id (for de-duplication), a per-device sequence number (for ordering)
and the device's own timestamp. Events delivered from the device's offline buffer set data.buffered = true.
"""

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

TOPIC_PREFIX = "fleet/v1/devices"
EVENTS_SUB = f"{TOPIC_PREFIX}/+/events"


def events_topic(serial: str) -> str:
    return f"{TOPIC_PREFIX}/{serial}/events"


def commands_topic(serial: str) -> str:
    return f"{TOPIC_PREFIX}/{serial}/commands"


def serial_from_topic(topic: str) -> str | None:
    parts = topic.split("/")
    return parts[3] if len(parts) == 5 and parts[4] == "events" else None


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")
    msg_id: str = Field(min_length=8, max_length=64)
    serial: str = Field(pattern=r"^MD-\d{5}$")
    seq: int = Field(ge=1)
    ts: datetime
    buffered: bool = False


class HeartbeatData(BaseModel):
    battery_pct: int = Field(ge=0, le=100)
    roll_remaining: int = Field(ge=0, le=100)
    firmware: str = Field(max_length=20)
    rssi_dbm: int = Field(ge=-130, le=0)


class Heartbeat(_Base):
    type: Literal["heartbeat"]
    data: HeartbeatData


class DoseData(BaseModel):
    due_at: datetime
    sachet_id: str | None = Field(default=None, max_length=40)


class DoseDue(_Base):
    type: Literal["dose_due"]
    data: DoseData


class DoseTaken(_Base):
    type: Literal["dose_taken"]
    data: DoseData


class DispenseFailedData(DoseData):
    reason: Literal["sachet_unreadable", "roll_empty", "jam"]


class DispenseFailed(_Base):
    type: Literal["dispense_failed"]
    data: DispenseFailedData


class CommandAckData(BaseModel):
    command_id: int
    ok: bool
    detail: str | None = Field(default=None, max_length=200)


class CommandAck(_Base):
    type: Literal["command_ack"]
    data: CommandAckData


class BootData(BaseModel):
    firmware: str
    boot_count: int = Field(ge=1)


class Boot(_Base):
    type: Literal["boot"]
    data: BootData


DeviceMessage = Annotated[Union[Heartbeat, DoseDue, DoseTaken, DispenseFailed, CommandAck, Boot],
                          Field(discriminator="type")]


_adapter = TypeAdapter(DeviceMessage)


def parse_message(raw: bytes | str) -> tuple[BaseModel | None, str | None]:
    """Returns (message, None) or (None, error description)."""
    try:
        return _adapter.validate_json(raw), None
    except ValidationError as e:
        err = e.errors()[0]
        loc = ".".join(str(p) for p in err.get("loc", [])[1:] if not isinstance(p, int))
        if err.get("type") == "json_invalid":
            return None, "Malformed JSON"
        return None, f"{loc or 'payload'}: {err.get('msg')}"[:300]


class CommandMessage(BaseModel):
    command_id: int
    type: str
    params: dict = {}
