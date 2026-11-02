# Dispenser Fleet Lab

[![CI](https://github.com/SaraEwaida/dispenser-fleet-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/SaraEwaida/dispenser-fleet-lab/actions/workflows/ci.yml)

A simulated fleet of connected medication dispensers, the cloud service that watches them, and the support console a care team and an L1 support engineer would use. Built as a QA and L1 support portfolio project.

Twenty-four virtual dispensers talk to the backend over real MQTT. They send heartbeats, dose reminders, button presses and dispense failures, and they misbehave the way field devices do: they drop offline and replay buffered events, send duplicates, corrupt payloads and drift their clocks. The backend has to turn that stream into correct alerts, and the tests prove it does.

> All devices, clients and data are synthetic. This is not a medical device and makes no compliance claims.

![Fleet overview](docs/screenshots/fleet.png)

## What it does

**For care coordination**
- Fleet overview: every dispenser's connection, battery, medication roll and 24-hour adherence, refreshed every few seconds.
- Alerts for missed doses, failed dispenses, offline devices, clock drift, low battery and empty rolls. Each severity has an acknowledgement SLA, and overdue alerts are flagged.
- Hand an alert over to support as a ticket in one step.

**For L1 support**
- Device pages with dose history, open alerts and the raw message log.
- Remote actions: resync the clock, re-send the schedule, reboot, simulate a roll change. Results come back from the device as acknowledgements.
- Schedule editor with validation, in the client's own timezone.
- Ticket workflow (open, investigating, escalated, resolved) with internal notes and a required resolution.
- Playbooks: what to check, what to do and when to escalate, for every alert type.

**For QA**
- Fault Lab: inject seven device-side faults into any dispenser and watch the cloud react.
- Message log with every message received, including duplicates and rejected payloads with the exact validation error.

| Alerts | Device |
|---|---|
| ![Alerts](docs/screenshots/alerts.png) | ![Device](docs/screenshots/device.png) |

| Fault Lab | Message log |
|---|---|
| ![Fault Lab](docs/screenshots/fault-lab.png) | ![Message log](docs/screenshots/messages.png) |

## Architecture

```mermaid
flowchart LR
  subgraph Process["One service (FastAPI process)"]
    SIM["Fleet simulator<br/>24 virtual dispensers<br/>(one MQTT client each)"]
    BROKER["MQTT broker<br/>(amqtt, embedded)"]
    ING["Ingestion<br/>validate, dedupe, order"]
    ENG["Escalation engine<br/>every 2 s"]
    DISP["Command dispatcher"]
    API["REST API /api/v1"]
  end
  SIM -- "fleet/v1/devices/{serial}/events" --> BROKER
  BROKER --> ING
  DISP -- "fleet/v1/devices/{serial}/commands" --> BROKER
  BROKER --> SIM
  ING --> DB[("PostgreSQL")]
  ENG --> DB
  DISP --> DB
  API --> DB
  UI["Support console<br/>React + TypeScript"] --> API
  FL["Fault Lab"] -. "faults table" .-> SIM
```

- **Simulated clock.** The fleet runs at 30x, so one fleet minute passes every two real seconds and a full day of doses happens in 48 minutes. Tests freeze and advance the clock instead of sleeping.
- **Faults live on the device side only.** Fault Lab writes to a `faults` table that only the simulator reads. The backend never knows a fault is active, so every detection is real.
- **Doses come from the schedule, not from the device.** The engine creates the expected doses from each client's schedule and timezone (DST-safe). A device that goes silent still produces missed-dose alerts.

## Device protocol

Topics: `fleet/v1/devices/{serial}/events` (device to cloud) and `fleet/v1/devices/{serial}/commands` (cloud to device), QoS 1.

```json
{"msg_id": "6f1c...", "serial": "MD-24004", "seq": 42, "ts": "2026-11-02T08:00:12+00:00",
 "type": "dose_taken", "buffered": false, "data": {"due_at": "2026-11-02T08:00:00+00:00"}}
```

Message types: `heartbeat`, `dose_due`, `dose_taken`, `dispense_failed`, `command_ack`, `boot`. Payloads are validated strictly (unknown fields rejected, serial must match the topic).

**Ingestion rules**
- Every message is logged, including rejected ones, with the reason.
- `msg_id` is the idempotency key: a repeat is logged as Duplicate and changes nothing.
- `seq` is a per-boot counter. Lower than the last seen means Out of order: flagged but still applied. A live `boot` starts a new sequence.
- `buffered: true` marks events stored while offline. They complete dose history but never overwrite current state or measure clock drift.
- A late dose confirmation turns a missed dose into Late and resolves its alert automatically.
- Battery alerts use hysteresis: raised below 20 %, resolved at 30 % or more, so they do not flap.

## Roles

| Role | Can do |
|---|---|
| Care Coordinator | See the fleet, acknowledge and resolve alerts, create tickets |
| Support Engineer | Everything above plus remote commands, schedule changes, message log, ticket workflow |
| QA Engineer | Read everything, send commands, inject and clear faults, create tickets |

Permissions are enforced by the API; the console only uses them to shape navigation.

## Demo accounts

Password for all accounts: `Demo@2026!`

| Email | Role |
|---|---|
| coordinator@fleet.example.com | Care Coordinator |
| support@fleet.example.com | Support Engineer |
| qa@fleet.example.com | QA Engineer |

The login page has one-click buttons for each.

## Run it locally

**With Docker**

```bash
docker compose up --build
# open http://localhost:8000
```

**Without Docker** (Python 3.13, Node 22, PostgreSQL 16)

```bash
createdb fleet
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://USER:PASSWORD@localhost:5432/fleet
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --port 8100
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to :8100
```

`python -m app.db.seed --reset` wipes and recreates the synthetic fleet.

## Tests

| Suite | Count | Command |
|---|---|---|
| Backend unit and integration (pytest, real PostgreSQL) | 69 | `cd backend && pytest` |
| MQTT end to end (real broker, simulated devices at 600x) | included above | `pytest tests/integration/test_end_to_end_mqtt.py` |
| Browser (Playwright, against the running fleet) | 7 | `cd e2e && npm ci && npx playwright test` |
| API (Postman / Newman) | 39 requests, 120 assertions | `npx newman run postman/Dispenser-Fleet-Lab.postman_collection.json -e postman/local.postman_environment.json` |

Backend tests need an empty database: `createdb fleet_test` (or set `TEST_DATABASE_URL`). Playwright expects the app on `http://localhost:8100` (override with `E2E_BASE_URL`). For Newman, set `baseUrl` in the environment file or pass `--env-var baseUrl=...`.

All four suites run on every push in GitHub Actions (`.github/workflows/ci.yml`); reports are uploaded as build artifacts.

Test names carry their test case ID (`test_tc016_...`, `[TC-044]`). See:

- [docs/test-cases.md](docs/test-cases.md): traceability from every case to its automated test, plus manual procedures.
- [docs/bug-reports.md](docs/bug-reports.md): real defects found while building this, with root cause, fix and regression test, and how a support ticket becomes an engineering bug.

## Fault Lab

| Fault | What the device does | What the cloud should do |
|---|---|---|
| Offline | Stops sending, buffers events | Offline alert after 15 fleet minutes; on reconnect accept buffered events and auto-resolve |
| Duplicate messages | Publishes every message twice | Log the copy as Duplicate, change nothing |
| Corrupt payload | Sends malformed or incomplete messages | Reject with a field-level reason |
| Clock drift | Jumps 25 minutes ahead; rejects resync | Clock drift alert; resync command reported as failed |
| No response | Client never presses the button | Missed dose alert 30 minutes after each due time |
| Read error | Cannot read the sachet, refuses to dispense | Dispense failed alert per dose |
| Battery drain | Backup battery drops fast | Battery low alert, resolved by recovery |

## Deployment

One Docker image runs the API, the console, the MQTT broker and the simulator. `render.yaml` deploys it as a free Render web service with an external PostgreSQL database (for example Neon). Set `DATABASE_URL` in the Render dashboard; `JWT_SECRET` is generated. Migrations and seeding run on start.

Free services sleep when idle. On wake-up the fleet resumes without a flood of offline or missed-dose alerts for the time it was asleep. The message log keeps the newest 100,000 rows (`TELEMETRY_KEEP_ROWS`) so the database stays within free-tier storage.

## Tech stack

FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, PostgreSQL 16, amqtt and aiomqtt (MQTT), JWT with bcrypt, React 19, TypeScript, Vite, Tailwind CSS 4, Radix UI, TanStack Query, Recharts, Playwright, Postman and Newman, Docker.

## Limitations

- The devices are simulated. Timing, battery and radio behaviour are simplified.
- The embedded MQTT broker has no authentication; it listens on localhost inside the container only. A real fleet would use per-device certificates.
- Demo accounts share a public password. Do not put real client data in a deployment.
- No independent security or compliance review has been done.
