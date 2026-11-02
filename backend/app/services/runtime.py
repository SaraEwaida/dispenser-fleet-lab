"""Background runtime: embedded MQTT broker, ingestion subscriber, escalation loop and command dispatcher."""

import asyncio
import json
import logging
from datetime import timedelta

import aiomqtt
from sqlalchemy import select, update
from starlette.concurrency import run_in_threadpool

from app.core.clock import get_clock
from app.core.config import get_settings
from app.core.protocol import EVENTS_SUB, commands_topic
from app.db.session import SessionLocal
from app.models import Command, CommandStatus, Device, DeviceStatus
from app.services.escalation import run_pass
from app.services.ingestion import process_raw

log = logging.getLogger("fleet.runtime")
for noisy in ("amqtt", "transitions", "hbmqtt"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


class Runtime:
    def __init__(self):
        self.broker = None
        self.tasks: list[asyncio.Task] = []
        self.lock = asyncio.Lock()   # serialises background DB writers so ingestion and escalation never race
        self.stats = {"received": 0, "errors": 0, "engine_passes": 0, "commands_sent": 0}
        self.publisher: aiomqtt.Client | None = None

    # ---------- broker ----------
    async def start_broker(self) -> None:
        from amqtt.broker import Broker
        s = get_settings()
        self.broker = Broker({
            "listeners": {"default": {"type": "tcp", "bind": f"{s.mqtt_host}:{s.mqtt_port}", "max_connections": 500}},
            "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
            "topic-check": {"enabled": False},
        })
        await self.broker.start()
        log.info("embedded MQTT broker listening on %s:%s", s.mqtt_host, s.mqtt_port)

    # ---------- startup ----------
    @staticmethod
    def resume_fleet() -> None:
        """Simulated time restarts with the process. Start expectations from now so downtime doesn't become a flood
        of 'missed' doses and 'offline' alerts for a period when the simulator simply wasn't running."""
        now = get_clock().now()
        with SessionLocal() as db:
            db.execute(update(Device).values(commissioned_at=now))
            db.execute(update(Device).where(Device.status != DeviceStatus.never_seen).values(last_seen_at=now))
            db.commit()

    # ---------- ingestion ----------
    def _ingest(self, topic: str, payload: bytes) -> None:
        with SessionLocal() as db:
            try:
                process_raw(db, topic, payload, get_clock().now())
                db.commit()
            except Exception:
                db.rollback()
                self.stats["errors"] += 1
                log.exception("ingestion failed for %s", topic)

    async def _ingest_loop(self) -> None:
        s = get_settings()
        while True:
            try:
                async with aiomqtt.Client(s.mqtt_host, s.mqtt_port, identifier="cloud-ingest", keepalive=30) as c:
                    await c.subscribe(EVENTS_SUB, qos=1)
                    async for m in c.messages:
                        self.stats["received"] += 1
                        async with self.lock:
                            await run_in_threadpool(self._ingest, str(m.topic), bytes(m.payload))
            except aiomqtt.MqttError as e:
                log.warning("ingest connection lost (%s); reconnecting", e)
                await asyncio.sleep(1)

    # ---------- escalation ----------
    def _engine_pass(self) -> None:
        with SessionLocal() as db:
            try:
                run_pass(db, get_clock().now())
                db.commit()
            except Exception:
                db.rollback()
                log.exception("escalation pass failed")

    async def _engine_loop(self) -> None:
        while True:
            async with self.lock:
                await run_in_threadpool(self._engine_pass)
            self.stats["engine_passes"] += 1
            await asyncio.sleep(get_settings().engine_tick_seconds)

    # ---------- commands ----------
    def _due_commands(self) -> list[tuple[int, str, str]]:
        with SessionLocal() as db:
            rows = db.execute(select(Command.id, Device.serial, Command.type).join(Device, Device.id == Command.device_id)
                              .where(Command.status == CommandStatus.queued, Device.status == DeviceStatus.online)
                              .order_by(Command.id)).all()
            return [(cid, serial, t.value) for cid, serial, t in rows]

    def _mark_sent(self, cid: int) -> None:
        with SessionLocal() as db:
            cmd = db.get(Command, cid)
            if cmd and cmd.status == CommandStatus.queued:
                cmd.status, cmd.sent_at = CommandStatus.sent, get_clock().now()
                db.commit()

    async def _dispatch_loop(self) -> None:
        s = get_settings()
        while True:
            try:
                async with aiomqtt.Client(s.mqtt_host, s.mqtt_port, identifier="cloud-commands") as c:
                    self.publisher = c
                    while True:
                        for cid, serial, ctype in await run_in_threadpool(self._due_commands):
                            await c.publish(commands_topic(serial), json.dumps({"command_id": cid, "type": ctype, "params": {}}), qos=1)
                            await run_in_threadpool(self._mark_sent, cid)
                            self.stats["commands_sent"] += 1
                        await asyncio.sleep(1)
            except aiomqtt.MqttError as e:
                self.publisher = None
                log.warning("command dispatcher lost connection (%s)", e)
                await asyncio.sleep(1)

    # ---------- lifecycle ----------
    async def start(self, simulator=None) -> None:
        s = get_settings()
        if s.mqtt_embedded:
            await self.start_broker()
        await run_in_threadpool(self.resume_fleet)
        self.tasks += [asyncio.create_task(self._ingest_loop(), name="ingest"),
                       asyncio.create_task(self._engine_loop(), name="escalation"),
                       asyncio.create_task(self._dispatch_loop(), name="dispatcher")]
        await asyncio.sleep(0.5)  # let the cloud subscribe before devices start publishing
        if simulator is not None:
            await simulator.start()

    async def stop(self, simulator=None) -> None:
        if simulator is not None:
            await simulator.stop()
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.broker is not None:
            await self.broker.shutdown()


runtime = Runtime()
