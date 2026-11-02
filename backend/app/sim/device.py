"""A virtual medication dispenser that speaks the fleet protocol over MQTT.

Behaviour (normal): heartbeat every few simulated minutes; at each scheduled time it signals the reminder
(dose_due) and, depending on the client's adherence, the client presses the button some minutes later
(dose_taken) and a sachet is dispensed from the roll.

Faults change *device* behaviour only; the cloud must cope:
  offline             disconnects and buffers events, flushes them (buffered=true) on reconnect
  duplicate_messages  publishes every event twice with the same msg_id
  corrupt_payload     about a third of messages are malformed or miss required fields
  clock_drift         device clock jumps 25 min ahead; resync is rejected while the fault is active
  no_response         client never presses the button
  read_error          sachet print unreadable: dispensing fails
  battery_drain       backup battery drains fast (as if unplugged)
"""

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timedelta

import aiomqtt

from app.core.clock import SimClock
from app.core.protocol import commands_topic, events_topic
from app.services.escalation import due_times

log = logging.getLogger("fleet.sim")
TICK_REAL_SECONDS = 0.5


class VirtualDevice:
    def __init__(self, serial: str, timezone: str, schedule: list[str], *, firmware: str, roll: int, roll_capacity: int,
                 adherence: float, clock: SimClock, host: str, port: int, faults_for, schedule_loader, seed: int,
                 heartbeat_minutes: int = 5):
        self.serial, self.tz, self.schedule = serial, timezone, schedule
        self.firmware, self.roll, self.roll_capacity = firmware, roll, roll_capacity
        self.adherence, self.clock, self.host, self.port = adherence, clock, host, port
        self.faults_for, self.schedule_loader = faults_for, schedule_loader
        self.rng = random.Random(seed)
        self.heartbeat_minutes = heartbeat_minutes
        self.battery = 100.0
        self.seq = 0
        self.boot_count = 1
        self.clock_offset = timedelta(0)
        self.drift_applied = False
        self.buffer: list[dict] = []
        self.pending_presses: dict[datetime, datetime] = {}
        self.client: aiomqtt.Client | None = None
        self.last_checked = clock.now()
        self.last_heartbeat: datetime | None = None
        self.stopped = False
        self.rssi = -self.rng.randint(55, 85)

    # ---------- helpers ----------
    @property
    def faults(self) -> set[str]:
        return self.faults_for(self.serial)

    def device_now(self) -> datetime:
        return self.clock.now() + self.clock_offset

    def _event(self, type_: str, data: dict) -> dict:
        self.seq += 1
        return {"msg_id": uuid.uuid4().hex, "serial": self.serial, "seq": self.seq,
                "ts": self.device_now().isoformat(), "type": type_, "data": data}

    async def emit(self, type_: str, data: dict) -> None:
        msg = self._event(type_, data)
        if self.client is None:
            self.buffer.append(msg)
            return
        await self._publish(msg)

    async def _publish(self, msg: dict) -> None:
        body = json.dumps(msg)
        if "corrupt_payload" in self.faults and self.rng.random() < 0.35:
            kind = self.rng.choice(["truncate", "drop_field", "bad_value"])
            if kind == "truncate":
                body = body[: len(body) // 2]
            elif kind == "drop_field":
                body = json.dumps({k: v for k, v in msg.items() if k != "ts"})
            else:
                body = json.dumps({**msg, "seq": "not-a-number"})
        copies = 2 if "duplicate_messages" in self.faults else 1
        for _ in range(copies):
            await self.client.publish(events_topic(self.serial), body, qos=1)

    async def _flush_buffer(self) -> None:
        pending, self.buffer = self.buffer, []
        for msg in pending:
            msg["buffered"] = True
            await self._publish(msg)

    async def heartbeat(self) -> None:
        self.last_heartbeat = self.clock.now()
        await self.emit("heartbeat", {"battery_pct": int(self.battery), "roll_remaining": self.roll,
                                      "firmware": self.firmware, "rssi_dbm": self.rssi + self.rng.randint(-3, 3)})

    # ---------- behaviour ----------
    async def tick(self) -> None:
        now = self.clock.now()
        faults = self.faults
        minutes = TICK_REAL_SECONDS * self.clock.speed / 60

        if "clock_drift" in faults and not self.drift_applied:
            self.clock_offset += timedelta(minutes=25)
            self.drift_applied = True
        if "clock_drift" not in faults:
            self.drift_applied = False

        if "battery_drain" in faults:
            self.battery = max(3.0, self.battery - 3 * minutes)
        else:
            self.battery = min(100.0, self.battery + 1 * minutes)  # mains power recharges the backup battery

        if self.last_heartbeat is None or now - self.last_heartbeat >= timedelta(minutes=self.heartbeat_minutes):
            await self.heartbeat()

        for due in due_times(self.schedule, self.tz, self.last_checked, now):
            await self.emit("dose_due", {"due_at": due.isoformat()})
            if "no_response" not in faults and self.rng.random() < self.adherence:
                self.pending_presses[due] = due + timedelta(minutes=self.rng.uniform(1, 25))
        self.last_checked = now

        for due, press_at in list(self.pending_presses.items()):
            if press_at > now:
                continue
            del self.pending_presses[due]
            if "no_response" in faults:
                continue
            if "read_error" in faults:
                await self.emit("dispense_failed", {"due_at": due.isoformat(), "reason": "sachet_unreadable"})
            elif self.roll == 0:
                await self.emit("dispense_failed", {"due_at": due.isoformat(), "reason": "roll_empty"})
            else:
                self.roll -= 1
                await self.emit("dose_taken", {"due_at": due.isoformat(), "sachet_id": f"{self.serial}-{uuid.uuid4().hex[:8]}"})

    async def handle_command(self, payload: bytes) -> None:
        try:
            cmd = json.loads(payload)
            cid, ctype = int(cmd["command_id"]), cmd["type"]
        except (ValueError, KeyError, TypeError):
            return
        ok, detail = True, "done"
        if ctype == "resync_clock":
            if "clock_drift" in self.faults:
                ok, detail = False, "RTC unstable: resync rejected (hardware clock fault)"
            else:
                detail = f"clock corrected by {int(-self.clock_offset.total_seconds() // 60):+d} min"
                self.clock_offset = timedelta(0)
        elif ctype == "reboot":
            self.boot_count += 1
        elif ctype == "sync_schedule":
            self.schedule = await self.schedule_loader(self.serial)
            detail = f"schedule {', '.join(self.schedule)}"
        elif ctype == "replace_roll":
            self.roll = self.roll_capacity
            detail = f"new roll loaded ({self.roll} sachets)"
        else:
            ok, detail = False, f"unknown command {ctype}"
        await self.emit("command_ack", {"command_id": cid, "ok": ok, "detail": detail})
        if ok and ctype == "reboot":
            await self.emit("boot", {"firmware": self.firmware, "boot_count": self.boot_count})
        if ok and ctype in ("replace_roll", "resync_clock", "reboot"):
            await self.heartbeat()

    async def run(self) -> None:
        """Connect, stay connected while healthy, buffer while 'offline', and reconnect after errors."""
        while not self.stopped:
            if "offline" in self.faults:
                self.client = None
                await self.tick()
                await asyncio.sleep(TICK_REAL_SECONDS)
                continue
            try:
                async with aiomqtt.Client(self.host, self.port, identifier=self.serial, keepalive=30) as c:
                    await c.subscribe(commands_topic(self.serial), qos=1)
                    self.client = c
                    reader = asyncio.create_task(self._read(c))
                    if self.buffer:
                        await self._flush_buffer()
                    if self.seq == 0:
                        await self.emit("boot", {"firmware": self.firmware, "boot_count": self.boot_count})
                    while not self.stopped and "offline" not in self.faults:
                        await self.tick()
                        await asyncio.sleep(TICK_REAL_SECONDS)
                    self.client = None
                    reader.cancel()
            except aiomqtt.MqttError as e:
                self.client = None
                log.debug("%s mqtt error: %s", self.serial, e)
                await asyncio.sleep(2)

    async def _read(self, c: aiomqtt.Client) -> None:
        async for m in c.messages:
            await self.handle_command(m.payload)
