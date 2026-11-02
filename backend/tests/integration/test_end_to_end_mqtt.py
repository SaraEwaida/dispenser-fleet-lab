"""End to end over real MQTT: embedded broker + cloud ingestion + escalation + a virtual dispenser.

Runs the simulated clock at 600x (1 real second = 10 simulated minutes) on a dedicated device so it is isolated
from the rest of the suite.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.core.clock import get_clock
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Alert, AlertStatus, AlertType, Device, DeviceStatus, Fault, FaultType, Telemetry, TelemetryStatus
from app.services.runtime import Runtime
from app.sim.device import VirtualDevice


def _state(serial):
    with SessionLocal() as db:
        d = db.scalars(select(Device).where(Device.serial == serial)).one()
        tele = db.scalars(select(Telemetry).where(Telemetry.serial == serial)).all()
        alerts = db.scalars(select(Alert).where(Alert.device_id == d.id)).all()
        return d, tele, alerts


def _set_fault(device_id, fault, on):
    with SessionLocal() as db:
        if on:
            db.add(Fault(device_id=device_id, type=fault))
        else:
            db.query(Fault).filter(Fault.device_id == device_id, Fault.type == fault).delete()
        db.commit()


def test_tc031_offline_buffer_flush_over_real_mqtt(make_device):
    s = get_settings()
    clock = get_clock()
    clock.unfreeze()
    clock.set_speed(600)
    d = make_device(schedule=("08:00",), commissioned=clock.now())
    faults: set[str] = set()

    async def scenario():
        rt = Runtime()
        await rt.start_broker()
        rt.tasks += [asyncio.create_task(rt._ingest_loop()), asyncio.create_task(rt._engine_loop())]
        await asyncio.sleep(0.5)
        dev = VirtualDevice(d.serial, "Europe/Amsterdam", ["08:00"], firmware="2.4.1", roll=20, roll_capacity=28,
                            adherence=1.0, clock=clock, host=s.mqtt_host, port=s.mqtt_port,
                            faults_for=lambda _: faults, schedule_loader=None, seed=1, heartbeat_minutes=5)
        task = asyncio.create_task(dev.run())
        try:
            await asyncio.sleep(2.0)                     # ~20 sim-min of healthy heartbeats
            dev_state, tele, _ = _state(d.serial)
            assert dev_state.status == DeviceStatus.online
            assert len(tele) >= 2 and all(t.status == TelemetryStatus.accepted for t in tele)

            faults.add("offline")                        # device drops off the network
            await asyncio.sleep(3.0)                     # ~30 sim-min: engine must notice (threshold 15)
            dev_state, _, alerts = _state(d.serial)
            assert dev_state.status == DeviceStatus.offline
            assert any(a.type == AlertType.device_offline and a.status == AlertStatus.open for a in alerts)
            assert dev.buffer, "device should buffer events while offline"

            faults.discard("offline")                    # reconnects and flushes the buffer
            await asyncio.sleep(2.0)
            dev_state, tele, alerts = _state(d.serial)
            assert dev_state.status == DeviceStatus.online
            buffered = [t for t in tele if t.buffered]
            assert buffered and all(t.status == TelemetryStatus.accepted for t in buffered)
            offline = [a for a in alerts if a.type == AlertType.device_offline]
            assert offline and all(a.status == AlertStatus.resolved for a in offline)
            assert not [a for a in alerts if a.type == AlertType.clock_drift], "buffered heartbeats must not count as drift"
        finally:
            dev.stopped = True
            task.cancel()
            await rt.stop()

    try:
        asyncio.run(scenario())
    finally:
        clock.set_speed(s.sim_speed)


def test_tc032_duplicates_and_corruption_over_real_mqtt(make_device):
    s = get_settings()
    clock = get_clock()
    clock.unfreeze()
    clock.set_speed(600)
    d = make_device(schedule=("08:00",), commissioned=clock.now())
    faults = {"duplicate_messages"}

    async def scenario():
        rt = Runtime()
        await rt.start_broker()
        rt.tasks.append(asyncio.create_task(rt._ingest_loop()))
        await asyncio.sleep(0.5)
        dev = VirtualDevice(d.serial, "Europe/Amsterdam", ["08:00"], firmware="2.4.1", roll=20, roll_capacity=28,
                            adherence=1.0, clock=clock, host=s.mqtt_host, port=s.mqtt_port,
                            faults_for=lambda _: faults, schedule_loader=None, seed=2, heartbeat_minutes=5)
        task = asyncio.create_task(dev.run())
        try:
            await asyncio.sleep(2.0)
            faults.clear()
            faults.add("corrupt_payload")
            await asyncio.sleep(3.0)
            _, tele, _ = _state(d.serial)
            by_status = {st: [t for t in tele if t.status == st] for st in TelemetryStatus}
            accepted_ids = [t.msg_id for t in by_status[TelemetryStatus.accepted]]
            assert by_status[TelemetryStatus.duplicate], "duplicates should be detected"
            assert len(accepted_ids) == len(set(accepted_ids)), "each msg_id applied once"
            assert by_status[TelemetryStatus.invalid], "corrupt payloads should be rejected"
        finally:
            dev.stopped = True
            task.cancel()
            await rt.stop()

    try:
        asyncio.run(scenario())
    finally:
        clock.set_speed(s.sim_speed)
