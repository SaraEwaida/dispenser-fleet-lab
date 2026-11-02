"""Starts one VirtualDevice per active device in the database and keeps their fault state in sync."""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.core.clock import SimClock
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Device, DoseSchedule, Fault
from app.sim.device import VirtualDevice

log = logging.getLogger("fleet.sim")

# Per-client adherence (probability of pressing the button). A few clients forget often, which keeps
# missed-dose alerts realistic without any fault being active.
ADHERENCE = [0.97, 0.95, 0.92, 0.9, 0.75]


class FleetSimulator:
    def __init__(self, clock: SimClock):
        self.clock = clock
        self.devices: dict[str, VirtualDevice] = {}
        self.tasks: list[asyncio.Task] = []
        self._faults: dict[str, set[str]] = {}
        self._refresher: asyncio.Task | None = None

    def faults_for(self, serial: str) -> set[str]:
        return self._faults.get(serial, set())

    def _load_faults(self) -> dict[str, set[str]]:
        with SessionLocal() as db:
            rows = db.execute(select(Device.serial, Fault.type).join(Fault, Fault.device_id == Device.id)).all()
        out: dict[str, set[str]] = {}
        for serial, f in rows:
            out.setdefault(serial, set()).add(f.value)
        return out

    @staticmethod
    def _load_schedule(serial: str) -> list[str]:
        with SessionLocal() as db:
            return list(db.scalars(select(DoseSchedule.time_of_day).join(Device, Device.id == DoseSchedule.device_id)
                                   .where(Device.serial == serial).order_by(DoseSchedule.time_of_day)))

    async def schedule_loader(self, serial: str) -> list[str]:
        return await run_in_threadpool(self._load_schedule, serial)

    async def start(self) -> None:
        s = get_settings()
        with SessionLocal() as db:
            devices = db.scalars(select(Device).where(Device.is_active)
                                 .options(selectinload(Device.schedule), selectinload(Device.client))
                                 .order_by(Device.id)).all()
            specs = [(d.serial, d.client.timezone, [x.time_of_day for x in d.schedule], d.firmware,
                      d.roll_remaining if d.roll_remaining is not None else d.roll_capacity, d.roll_capacity, d.id)
                     for d in devices]
        self._faults = await run_in_threadpool(self._load_faults)
        for i, (serial, tz, schedule, fw, roll, cap, dev_id) in enumerate(specs):
            vd = VirtualDevice(serial, tz, schedule, firmware=fw, roll=roll, roll_capacity=cap,
                               adherence=ADHERENCE[i % len(ADHERENCE)], clock=self.clock, host=s.mqtt_host,
                               port=s.mqtt_port, faults_for=self.faults_for, schedule_loader=self.schedule_loader,
                               seed=s.sim_seed + dev_id, heartbeat_minutes=s.heartbeat_interval_minutes)
            self.devices[serial] = vd
            self.tasks.append(asyncio.create_task(vd.run(), name=f"device-{serial}"))
        self._refresher = asyncio.create_task(self._refresh_faults())
        log.info("fleet simulator started with %d devices", len(self.devices))

    async def _refresh_faults(self) -> None:
        while True:
            try:
                self._faults = await run_in_threadpool(self._load_faults)
            except Exception:  # keep the simulator alive through transient DB errors
                log.exception("fault refresh failed")
            await asyncio.sleep(1)

    async def stop(self) -> None:
        for vd in self.devices.values():
            vd.stopped = True
        if self._refresher:
            self._refresher.cancel()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
