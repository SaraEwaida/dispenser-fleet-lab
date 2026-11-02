import itertools
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.core.clock import get_clock
from app.core.security import login_limiter
from app.db import seed
from app.db.session import SessionLocal
from app.models import Client, Device, DoseSchedule
from app.services.ingestion import process_raw

API = "/api/v1"
T0 = datetime(2026, 11, 2, 7, 0, tzinfo=UTC)   # 08:00 in Amsterdam
_serials = itertools.count(90001)


@pytest.fixture(scope="session", autouse=True)
def database():
    assert "test" in os.environ["DATABASE_URL"], "Refusing to run against a non-test database."
    here = os.path.dirname(__file__)
    cfg = Config(os.path.join(here, "..", "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "..", "..", "alembic"))
    command.upgrade(cfg, "head")
    get_clock().freeze(T0)
    seed.run(reset=True)
    yield


@pytest.fixture(autouse=True)
def frozen_clock():
    get_clock().freeze(T0)
    login_limiter.reset()
    yield get_clock()


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def make_device(db):
    def _make(schedule=("08:00", "20:00"), tz="Europe/Amsterdam", commissioned=T0 - timedelta(hours=2)) -> Device:
        c = Client(display_name="Mrs. T. Testcase", care_team="Team Test", timezone=tz)
        db.add(c)
        db.flush()
        d = Device(serial=f"MD-{next(_serials)}", client_id=c.id, firmware="2.4.1", roll_remaining=20,
                   commissioned_at=commissioned)
        d.schedule = [DoseSchedule(time_of_day=t) for t in schedule]
        db.add(d)
        db.commit()
        return d
    return _make


class Sender:
    """Builds protocol messages and runs them through ingestion like the MQTT subscriber does."""

    def __init__(self, db, serial: str):
        self.db, self.serial, self.seq = db, serial, 0

    def __call__(self, type_: str, data: dict, *, at: datetime, now: datetime | None = None, seq: int | None = None,
                 msg_id: str | None = None, buffered: bool = False, topic_serial: str | None = None, raw: bytes | None = None):
        if seq is None:
            self.seq += 1
            seq = self.seq
        body = raw or json.dumps({"msg_id": msg_id or uuid.uuid4().hex, "serial": self.serial, "seq": seq,
                                  "ts": at.isoformat(), "type": type_, "data": data, "buffered": buffered}).encode()
        t = process_raw(self.db, f"fleet/v1/devices/{topic_serial or self.serial}/events", body, now or at)
        self.db.commit()
        return t

    def heartbeat(self, at, now=None, battery=95, roll=20, **kw):
        return self("heartbeat", {"battery_pct": battery, "roll_remaining": roll, "firmware": "2.4.1", "rssi_dbm": -70},
                    at=at, now=now, **kw)


@pytest.fixture
def sender(db):
    return lambda serial: Sender(db, serial)


@pytest.fixture(scope="session")
def client():
    with TestClient(__import__("app.main", fromlist=["app"]).app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for role in ("coordinator", "support", "qa"):
        r = client.post(f"{API}/auth/login", json={"email": f"{role}@fleet.example.com", "password": seed.DEMO_PASSWORD})
        assert r.status_code == 200, r.text
        out[role] = r.json()["access_token"]
    return out


@pytest.fixture
def auth(tokens):
    return lambda role="support": {"Authorization": f"Bearer {tokens[role]}"}
