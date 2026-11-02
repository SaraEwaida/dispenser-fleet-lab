"""Point every test at the test database before the app (and its engine) is imported.
Background services are off for API tests; the end-to-end test starts its own broker and devices."""

import os

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://medicare:medicare@localhost:5432/fleet_test")
os.environ["BACKGROUND_ENABLED"] = "false"
os.environ["MQTT_PORT"] = os.environ.get("TEST_MQTT_PORT", "18883")
os.environ["CORS_ORIGINS"] = ""
