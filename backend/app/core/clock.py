"""Simulated fleet clock.

The fleet runs on accelerated time (default 30x: a 24-hour medication day passes in 48 real minutes) so that
dose reminders, missed doses and escalations happen during a demo. Every component that reasons about time
(simulator, ingestion, escalation engine, API) reads this one clock.
"""

import threading
import time
from datetime import UTC, datetime, timedelta


class SimClock:
    def __init__(self, speed: float = 30.0, start: datetime | None = None):
        self._lock = threading.Lock()
        self._speed = speed
        self._anchor_real = time.monotonic()
        self._anchor_sim = start or datetime.now(UTC)
        self._frozen: datetime | None = None

    @property
    def speed(self) -> float:
        return self._speed

    def now(self) -> datetime:
        with self._lock:
            if self._frozen is not None:
                return self._frozen
            elapsed = time.monotonic() - self._anchor_real
            return self._anchor_sim + timedelta(seconds=elapsed * self._speed)

    def real_seconds(self, sim_minutes: float) -> float:
        """How many real seconds a span of simulated minutes takes."""
        return sim_minutes * 60 / self._speed

    # ---- test helpers -------------------------------------------------------------------------------------
    def freeze(self, at: datetime) -> None:
        with self._lock:
            self._frozen = at

    def advance(self, minutes: float) -> datetime:
        with self._lock:
            if self._frozen is None:
                raise RuntimeError("advance() only works on a frozen clock")
            self._frozen = self._frozen + timedelta(minutes=minutes)
            return self._frozen

    def unfreeze(self) -> None:
        with self._lock:
            now = self._frozen or datetime.now(UTC)
            self._frozen = None
            self._anchor_real = time.monotonic()
            self._anchor_sim = now

    def set_speed(self, speed: float) -> None:
        with self._lock:
            current = self._frozen or (self._anchor_sim + timedelta(
                seconds=(time.monotonic() - self._anchor_real) * self._speed))
            self._anchor_real, self._anchor_sim, self._speed = time.monotonic(), current, speed


_clock: SimClock | None = None


def get_clock() -> SimClock:
    global _clock
    if _clock is None:
        from app.core.config import get_settings
        _clock = SimClock(get_settings().sim_speed)
    return _clock
