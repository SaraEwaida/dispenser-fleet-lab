from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_version: str = "1.0.0"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://medicare:medicare@localhost:5432/fleet"

    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60
    login_attempts_per_minute: int = 5

    # MQTT. With mqtt_embedded the broker runs inside this process (single-container deploys).
    mqtt_embedded: bool = True
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883

    # Simulation
    simulator_enabled: bool = True
    background_enabled: bool = True     # ingestion, escalation engine, command dispatcher
    fleet_size: int = 24
    sim_speed: float = 30.0             # simulated seconds per real second
    sim_seed: int = 2026

    # Escalation rules, in simulated minutes
    dose_grace_minutes: int = 30        # no confirmation this long after due time -> missed dose
    heartbeat_interval_minutes: int = 5
    offline_after_minutes: int = 15
    clock_drift_threshold_minutes: int = 5
    battery_low_pct: int = 20
    roll_low_sachets: int = 2
    command_expiry_minutes: int = 60

    engine_tick_seconds: float = 2.0    # real seconds between escalation passes
    telemetry_keep_rows: int = 100_000  # message log retention; older rows are pruned (free-tier storage)

    cors_origins: str = "http://localhost:5173"
    frontend_dist: str = ""

    @field_validator("database_url")
    @classmethod
    def normalize_driver(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
