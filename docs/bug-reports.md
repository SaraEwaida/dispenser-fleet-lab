# Bug reports

Real defects found while building and testing this project, written up the way I would file them for an engineering team. Each has a regression test.

---

## BUG-001 Every login returns 500

| | |
|---|---|
| **Severity** | Critical (nobody can sign in) |
| **Priority** | P1 |
| **Environment** | Local, backend at commit before `jwt_algorithm` was added |
| **Found by** | First manual login after wiring auth |

**Steps to reproduce**
1. Start the backend.
2. `POST /api/v1/auth/login` with `support@fleet.example.com` / `Demo@2026!`.

**Expected:** 200 with a bearer token.
**Actual:** 500 Internal Server Error. Response carried a request ID.

**Investigation:** Searched the server log for the request ID: `AttributeError: 'Settings' object has no attribute 'jwt_algorithm'`. The security module was reused from another project whose settings had the field; this project's `Settings` did not.

**Fix:** Added `jwt_algorithm: str = "HS256"` to `Settings`.

**Verification:** `test_api.py::test_tc024_login_and_generic_failure` logs in every role and checks the generic 401 message.

---

## BUG-002 Missed-dose alert does not say the device is offline

| | |
|---|---|
| **Severity** | High (wrong information to the care team) |
| **Priority** | P2 |
| **Environment** | Escalation engine, any fleet speed |

**Preconditions:** A device with a dose due at 08:00.

**Steps to reproduce**
1. Inject Offline on the device at 07:50.
2. Let fleet time pass 08:30.
3. Open the Missed dose alert.

**Expected:** The alert says the device is offline, so the coordinator knows the client may have taken the dose and the confirmation is stuck in the device buffer.
**Actual:** "No confirmation for the 08:00 dose." The coordinator calls the client about a dose they probably took.

**Root cause:** `run_pass` checked missed doses before offline detection. At 08:30 the device had been silent for 40 minutes, but its status was still Online in the same pass, so the message builder did not mention it.

**Fix:** Run offline detection before the missed-dose check.

**Verification:** `test_escalation.py::test_tc020_missed_alert_mentions_offline_device`.

---

## BUG-003 After a server restart every message is flagged "Out of order"

| | |
|---|---|
| **Severity** | Medium (log noise hides real ordering problems; no data lost) |
| **Priority** | P2 |
| **Environment** | Running fleet, after a restart of the service (also any real device power cycle) |
| **Found by** | Screenshot review of the message log |

**Steps to reproduce**
1. Run the fleet for a few minutes.
2. Restart the service.
3. Message log, flag Out of order.

**Expected:** Messages after the restart are in order.
**Actual:** Almost every heartbeat from every device is flagged Out of order (71 of the last 200 messages).

**Investigation:** Message log for MD-24005: before the restart seq reached 10. After it, the device sent `boot` with seq 1, then heartbeats with seq 2, 3, 4… All were `<= last_seq` (10), so all were flagged.

**Root cause:** The device sequence counter restarts at 1 on every power-on, but the cloud's high-water mark (`devices.last_seq`) never resets. The protocol already sends a `boot` message first after power-on, but ingestion ignored it for ordering.

**Fix:** A live (not buffered) `boot` message starts a new sequence: it is never out of order and sets `last_seq` to its own seq. A buffered `boot` replayed after an outage is history and does not reset anything.

**Verification:** `test_ingestion.py::test_tc033_boot_starts_a_new_sequence` covers both cases. Confirmed live: after the fix, messages since the restart have no out-of-order flags.

---

## BUG-004 Fault Lab rows move while you toggle them

| | |
|---|---|
| **Severity** | Low (usability; can lead to toggling the wrong device) |
| **Priority** | P3 |
| **Environment** | Fault Lab page |

**Steps to reproduce**
1. Fault Lab, inject a fault on a device low in the list.
2. Wait for it to raise an alert.

**Expected:** The matrix stays in the same order.
**Actual:** The row jumps to the top, because the page reused the device list ordering (devices with open alerts first). The next click can hit a different device.

**Fix:** The matrix sorts by serial.

**Verification:** Manual (TC-042 manual variant). Playwright tests address cells by `data-testid` (serial and fault), which does not depend on order.

---

## From support ticket to engineering bug

How a ticket becomes a bug like the ones above:

1. **Ticket.** The caller's words go in the description. L1 follows the playbook for the alert type.
2. **Collect evidence.** Device serial, alert code, time window, and the msg_ids of the relevant messages from the message log. Every API error shows a request ID; copy it.
3. **Decide.** If the device or cloud did something the spec says it should not (a duplicate counted twice, an alert that should have resolved, a command that never completed), it is a defect. Escalate the ticket and add a note with the evidence.
4. **Reproduce in Fault Lab.** Use the fault that matches the field symptom on a simulated device. A defect that reproduces becomes a bug report with steps, expected and actual.
5. **Close the loop.** The fix ships with a regression test named after the test case. The ticket is resolved with the bug ID in the resolution.
