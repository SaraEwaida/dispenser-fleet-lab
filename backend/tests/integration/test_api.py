from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Alert, AlertType, Command, CommandStatus
from app.services.alerts import raise_alert
from tests.integration.conftest import API, T0


def test_tc024_login_and_generic_failure(client):
    ok = client.post(f"{API}/auth/login", json={"email": "QA@fleet.example.com", "password": "Demo@2026!"})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "qa_engineer"
    bad = client.post(f"{API}/auth/login", json={"email": "qa@fleet.example.com", "password": "nope"})
    unknown = client.post(f"{API}/auth/login", json={"email": "nobody@fleet.example.com", "password": "nope"})
    assert bad.status_code == unknown.status_code == 401
    assert bad.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert bad.json()["error"]["request_id"] == bad.headers["X-Request-ID"]


def test_successful_logins_are_not_rate_limited(client):
    for _ in range(7):
        assert client.post(f"{API}/auth/login", json={"email": "support@fleet.example.com", "password": "Demo@2026!"}).status_code == 200


@pytest.mark.parametrize("role,method,path,body", [
    ("coordinator", "post", "/devices/MD-24001/commands", {"type": "reboot"}),
    ("coordinator", "get", "/messages", None),
    ("support", "post", "/devices/MD-24001/faults", {"type": "offline"}),
    ("qa", "put", "/devices/MD-24001/schedule", {"times": ["08:00"]}),
    ("qa", "post", "/alerts/1/acknowledge", None),
    ("coordinator", "post", "/tickets/1/status", {"status": "resolved", "resolution": "x"}),
])
def test_tc025_role_restrictions(client, auth, role, method, path, body):
    r = getattr(client, method)(f"{API}{path}", headers=auth(role), **({"json": body} if body is not None else {}))
    assert r.status_code == 403, r.text


def test_tc026_alert_ack_and_resolve_workflow(client, auth, db, make_device):
    d = make_device()
    a = raise_alert(db, d, AlertType.missed_dose, "No confirmation for the 08:00 dose.", T0)
    db.commit()
    r = client.post(f"{API}/alerts/{a.id}/resolve", headers=auth("coordinator"), json={"resolution": "ok"})
    assert r.status_code == 422  # resolution too short
    r = client.post(f"{API}/alerts/{a.id}/acknowledge", headers=auth("coordinator"))
    assert r.json()["status"] == "acknowledged" and r.json()["acknowledged_by"] == "Carla Coordinator"
    assert client.post(f"{API}/alerts/{a.id}/acknowledge", headers=auth("coordinator")).status_code == 409
    r = client.post(f"{API}/alerts/{a.id}/resolve", headers=auth("coordinator"),
                    json={"resolution": "Called client: dose taken, button pressed too gently."})
    assert r.json()["status"] == "resolved" and not r.json()["auto_resolved"]


def test_tc027_overdue_alerts_are_flagged(client, auth, db, make_device, frozen_clock):
    d = make_device()
    a = raise_alert(db, d, AlertType.dispense_failed, "Sachet unreadable.", T0)  # high: 15 min SLA
    db.commit()
    frozen_clock.advance(14)
    items = client.get(f"{API}/alerts", params={"serial": d.serial}, headers=auth()).json()["items"]
    assert items[0]["overdue"] is False
    frozen_clock.advance(2)
    items = client.get(f"{API}/alerts", params={"serial": d.serial}, headers=auth()).json()["items"]
    assert items[0]["overdue"] is True
    assert any(x["id"] == a.id for x in client.get(f"{API}/alerts", params={"overdue": True}, headers=auth()).json()["items"])


def test_tc028_command_queued_and_duplicate_rejected(client, auth, db):
    r = client.post(f"{API}/devices/MD-24002/commands", headers=auth("support"), json={"type": "resync_clock"})
    assert r.status_code == 201 and r.json()["status"] == "queued"
    assert "not online" in r.json()["note"]  # seeded device has never connected in tests
    r2 = client.post(f"{API}/devices/MD-24002/commands", headers=auth("support"), json={"type": "resync_clock"})
    assert r2.status_code == 409 and r2.json()["error"]["code"] == "COMMAND_PENDING"
    assert client.post(f"{API}/devices/MD-24002/commands", headers=auth("support"), json={"type": "selfdestruct"}).status_code == 422


def test_tc029_schedule_validation_and_sync_command(client, auth, db):
    for bad in (["25:00"], ["08:00", "08:00"], [], ["8:00"], ["08:00"] * 7):
        assert client.put(f"{API}/devices/MD-24003/schedule", headers=auth("support"), json={"times": bad}).status_code == 422, bad
    r = client.put(f"{API}/devices/MD-24003/schedule", headers=auth("support"), json={"times": ["20:00", "08:00"]})
    assert r.json()["schedule"] == ["08:00", "20:00"]
    cmd = db.scalars(select(Command).order_by(Command.id.desc())).first()
    assert cmd.type.value == "sync_schedule" and cmd.status == CommandStatus.queued


def test_tc030_fault_lab_enable_disable(client, auth):
    h = auth("qa")
    assert client.post(f"{API}/devices/MD-24004/faults", headers=h, json={"type": "offline"}).status_code == 201
    r = client.post(f"{API}/devices/MD-24004/faults", headers=h, json={"type": "offline"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FAULT_ACTIVE"
    active = client.get(f"{API}/faults", headers=h).json()["active"]
    assert {"serial": "MD-24004", "type": "offline"}.items() <= next(a for a in active if a["serial"] == "MD-24004").items()
    assert client.delete(f"{API}/devices/MD-24004/faults/offline", headers=h).status_code == 204
    assert client.delete(f"{API}/devices/MD-24004/faults/offline", headers=h).status_code == 404
    assert client.post(f"{API}/devices/MD-24004/faults", headers=h, json={"type": "meteor"}).status_code == 422


def test_ticket_from_alert_and_workflow(client, auth, db, make_device):
    d = make_device()
    a = raise_alert(db, d, AlertType.device_offline, "No messages for 20 min.", T0)
    db.commit()
    r = client.post(f"{API}/tickets", headers=auth("coordinator"), json={
        "subject": "Dispenser offline at client home", "description": "Care team reports the display is dark.",
        "reporter": "Team North", "alert_id": a.id, "priority": "high"})
    assert r.status_code == 201 and r.json()["device_serial"] == d.serial
    tid = r.json()["id"]
    assert client.post(f"{API}/tickets/{tid}/status", headers=auth("support"), json={"status": "resolved"}).status_code == 422
    client.post(f"{API}/tickets/{tid}/notes", headers=auth("support"), json={"body": "Power adapter was unplugged."})
    r = client.post(f"{API}/tickets/{tid}/status", headers=auth("support"),
                    json={"status": "resolved", "resolution": "Caregiver plugged the adapter back in; device online."})
    assert r.json()["status"] == "resolved" and r.json()["notes"][0]["author"] == "Sam Support"
    assert client.get(f"{API}/alerts/{a.id}", headers=auth()).json()["tickets"][0]["id"] == tid


def test_ticket_rejects_alert_device_mismatch(client, auth, db, make_device):
    d1, d2 = make_device(), make_device()
    a = raise_alert(db, d1, AlertType.battery_low, "Battery 10%.", T0)
    db.commit()
    r = client.post(f"{API}/tickets", headers=auth("support"), json={
        "subject": "Battery issue", "description": "Battery keeps dropping.", "reporter": "Team",
        "alert_id": a.id, "device_serial": d2.serial})
    assert r.status_code == 422


def test_device_list_detail_and_filters(client, auth):
    page = client.get(f"{API}/devices", params={"q": "MD-2400", "page_size": 5}, headers=auth("coordinator")).json()
    assert page["total"] >= 9 and len(page["items"]) == 5
    detail = client.get(f"{API}/devices/MD-24001", headers=auth()).json()
    assert detail["schedule"] and detail["client"]["code"].startswith("C-")
    assert client.get(f"{API}/devices/MD-00000", headers=auth()).status_code == 404


def test_fleet_summary_shape(client, auth):
    s = client.get(f"{API}/fleet/summary", headers=auth("coordinator")).json()
    assert {"devices", "alerts", "doses_24h", "messages_1h", "dose_series", "adherence_24h"} <= s.keys()
    assert s["devices"]["total"] >= 24


def test_message_log_filters(client, auth, make_device, sender):
    d = make_device()
    sender(d.serial).heartbeat(T0, msg_id="filter-0001")
    sender(d.serial).heartbeat(T0, msg_id="filter-0001")
    items = client.get(f"{API}/messages", params={"serial": d.serial, "status": "duplicate"}, headers=auth("qa")).json()["items"]
    assert len(items) == 1 and items[0]["error"] == "msg_id already processed"


def test_message_log_retention_keeps_newest_rows(db, make_device, sender, monkeypatch):
    from app.core.config import get_settings
    from app.models import Telemetry
    from app.services.runtime import Runtime
    from sqlalchemy import func, select

    d = make_device()
    s = sender(d.serial)
    for i in range(6):
        s.heartbeat(T0 + timedelta(minutes=5 * i))
    monkeypatch.setattr(get_settings(), "telemetry_keep_rows", 4)
    top = db.scalar(select(func.max(Telemetry.id)))
    Runtime()._prune_telemetry()
    db.expire_all()
    ids = db.scalars(select(Telemetry.id)).all()
    assert len(ids) == 4 and min(ids) == top - 3
