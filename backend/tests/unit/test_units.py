"""Pure unit tests: protocol validation, schedule maths (incl. DST), simulated clock, permissions."""

import json
from datetime import UTC, datetime

import pytest

from app.core.clock import SimClock
from app.core.permissions import has_permission
from app.core.protocol import parse_message, serial_from_topic
from app.models import Role
from app.services.escalation import due_times

HB = {"msg_id": "a1b2c3d4e5", "serial": "MD-24001", "seq": 1, "ts": "2026-11-02T10:00:00Z", "type": "heartbeat",
      "data": {"battery_pct": 90, "roll_remaining": 20, "firmware": "2.4.1", "rssi_dbm": -70}}


def raw(**override) -> bytes:
    return json.dumps({**HB, **override}).encode()


def test_valid_heartbeat_parses():
    msg, err = parse_message(raw())
    assert err is None and msg.type == "heartbeat" and msg.data.battery_pct == 90


@pytest.mark.parametrize("payload,expected", [
    (b'{"msg_id": "abc', "Malformed JSON"),
    (raw(data={**HB["data"], "battery_pct": 101}), "data.battery_pct"),
    (raw(serial="XX-1"), "serial"),
    (raw(seq=0), "seq"),
    (raw(type="teleport"), "does not match"),
    (raw(extra_field=1), "extra"),
])
def test_invalid_payloads_are_rejected_with_reason(payload, expected):
    msg, err = parse_message(payload)
    assert msg is None and expected.lower() in err.lower()


def test_missing_timestamp_rejected():
    body = {k: v for k, v in HB.items() if k != "ts"}
    msg, err = parse_message(json.dumps(body))
    assert msg is None and "ts" in err


def test_serial_from_topic():
    assert serial_from_topic("fleet/v1/devices/MD-24001/events") == "MD-24001"
    assert serial_from_topic("fleet/v1/devices/MD-24001/commands") is None
    assert serial_from_topic("garbage") is None


def utc(*a):
    return datetime(*a, tzinfo=UTC)


def test_due_times_in_client_timezone():
    # Amsterdam is UTC+1 in winter: 08:00 local = 07:00 UTC.
    times = due_times(["08:00", "20:00"], "Europe/Amsterdam", utc(2026, 11, 2, 0, 0), utc(2026, 11, 2, 23, 59))
    assert times == [utc(2026, 11, 2, 7, 0), utc(2026, 11, 2, 19, 0)]


def test_due_times_window_is_exclusive_start_inclusive_end():
    t = due_times(["08:00"], "Europe/Amsterdam", utc(2026, 11, 2, 7, 0), utc(2026, 11, 3, 7, 0))
    assert t == [utc(2026, 11, 3, 7, 0)]


def test_due_times_across_dst_spring_forward():
    # 2026-03-29: clocks go 02:00 -> 03:00 in Amsterdam. 08:00 local is UTC+1 before and UTC+2 after.
    t = due_times(["08:00"], "Europe/Amsterdam", utc(2026, 3, 28, 0, 0), utc(2026, 3, 29, 23, 0))
    assert t == [utc(2026, 3, 28, 7, 0), utc(2026, 3, 29, 6, 0)]


def test_due_times_across_dst_fall_back():
    # 2026-10-25: clocks go 03:00 -> 02:00. A dose still occurs exactly once per day.
    t = due_times(["08:00"], "Europe/Amsterdam", utc(2026, 10, 24, 0, 0), utc(2026, 10, 25, 23, 0))
    assert t == [utc(2026, 10, 24, 6, 0), utc(2026, 10, 25, 7, 0)]


def test_sim_clock_freeze_and_advance():
    c = SimClock(speed=30)
    c.freeze(utc(2026, 1, 1, 8, 0))
    assert c.advance(30) == utc(2026, 1, 1, 8, 30)
    assert c.real_seconds(30) == 60  # 30 simulated minutes take 60 real seconds at 30x


def test_sim_clock_runs_faster_than_real_time():
    import time
    c = SimClock(speed=600)
    a = c.now()
    time.sleep(0.05)
    assert (c.now() - a).total_seconds() >= 25  # ~30 simulated seconds in 50 ms


@pytest.mark.parametrize("role,perm,ok", [
    (Role.care_coordinator, "alerts:handle", True), (Role.care_coordinator, "devices:command", False),
    (Role.care_coordinator, "telemetry:read", False), (Role.support_engineer, "devices:command", True),
    (Role.support_engineer, "faults:manage", False), (Role.qa_engineer, "faults:manage", True),
    (Role.qa_engineer, "alerts:handle", False), (Role.qa_engineer, "devices:schedule", False),
])
def test_permission_matrix(role, perm, ok):
    assert has_permission(role, perm) is ok
