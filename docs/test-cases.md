# Test cases

Every case has an ID that appears in the automated test name (`test_tc016_...` in pytest, `[TC-041]` in Playwright), so a failing test points straight back to this page.

Demo password for all accounts: `Demo@2026!`. The fleet runs at 30x: one fleet minute is two real seconds.

## Traceability

| ID | What it proves | Layer | Automated by |
|---|---|---|---|
| TC-001 | A heartbeat updates battery, roll, firmware, signal and last-seen | Ingestion | `test_ingestion.py::test_tc001` |
| TC-002 | A repeated `msg_id` is logged as Duplicate and changes nothing | Ingestion | `test_tc002` |
| TC-003 | A malformed payload is logged as Invalid with a field-level reason | Ingestion | `test_tc003` |
| TC-004 | Unknown serials and topic/payload serial mismatches are rejected | Ingestion | `test_tc004` |
| TC-005 | Out-of-order messages are flagged but still applied; `last_seq` never goes backwards | Ingestion | `test_tc005` |
| TC-006 | A buffered heartbeat never triggers a clock drift alert | Ingestion | `test_tc006` |
| TC-007 | A live skewed clock raises Clock drift; resync resolves it | Ingestion | `test_tc007` |
| TC-008 | Drift threshold boundary: 5 min exactly does not alert, 5 min 1 s does | Ingestion | `test_tc008` |
| TC-009 | A late confirmation turns a missed dose into Late and auto-resolves its alert | Ingestion | `test_tc009` |
| TC-010 | Each failed dispense raises one high-severity alert | Ingestion | `test_tc010` |
| TC-011 | Battery alert hysteresis: raise below 20 %, resolve at 30 % or more | Ingestion | `test_tc011` |
| TC-012 | Roll low, roll empty, and reset after a roll change | Ingestion | `test_tc012` |
| TC-013 | A command acknowledgement completes the command with the device's result | Ingestion | `test_tc013` |
| TC-014 | Any accepted message after an outage resolves the offline alert | Ingestion | `test_tc014` |
| TC-015 | Doses are expected from the schedule even if the device sends nothing | Escalation | `test_escalation.py::test_tc015` |
| TC-016 | Missed-dose grace boundary (30 min) | Escalation | `test_tc016` |
| TC-017 | Running the engine twice raises no duplicate alerts | Escalation | `test_tc017` |
| TC-018 | A confirmed dose is never escalated | Escalation | `test_tc018` |
| TC-019 | Offline threshold boundary (15 min) | Escalation | `test_tc019` |
| TC-020 | A missed-dose alert says when the device is offline (BUG-002 regression) | Escalation | `test_tc020` |
| TC-021 | No doses are expected before a device was commissioned | Escalation | `test_tc021` |
| TC-022 | Dose times follow the client's timezone, including DST changes | Escalation + unit | `test_tc022`, `test_due_times_across_dst_*` |
| TC-023 | A command that is never delivered expires after 60 fleet minutes | Escalation | `test_tc023` |
| TC-024 | Login works; a failed login gives a generic message | API | `test_api.py::test_tc024` |
| TC-025 | Each role is limited to its permissions (403) | API | `test_tc025`, `test_permission_matrix` |
| TC-026 | Alert acknowledge and resolve workflow; resolution note required | API | `test_tc026` |
| TC-027 | Alerts past their acknowledgement SLA are flagged overdue | API | `test_tc027` |
| TC-028 | A command is queued; a second identical pending command is rejected (409) | API | `test_tc028` |
| TC-029 | Schedule validation, and saving queues a `sync_schedule` command | API | `test_tc029` |
| TC-030 | Fault Lab enable, duplicate (409), disable, clear all | API | `test_tc030` |
| TC-031 | Offline buffer is flushed over a real MQTT broker and flagged Buffered | MQTT end to end | `test_end_to_end_mqtt.py::test_tc031` |
| TC-032 | Duplicates and corrupt payloads over a real MQTT broker | MQTT end to end | `test_tc032` |
| TC-033 | A boot message starts a new sequence (BUG-003 regression) | Ingestion | `test_tc033` |
| TC-040 | Each role sees only its navigation; restricted pages are blocked | Browser | `console.spec.ts [TC-040]` |
| TC-041 | Fault injection by a non-QA role is rejected with a request ID | Browser/API | `[TC-041]` |
| TC-042 | Clock drift: alert, resync rejected while faulty, accepted after clearing | Browser | `[TC-042]` |
| TC-043 | Duplicate messages appear as Duplicate in the message log | Browser | `[TC-043]` |
| TC-044 | Offline: alert, buffered delivery on reconnect, auto-resolve | Browser | `[TC-044]` |
| TC-045 | Schedule editor validation and device sync | Browser | `[TC-045]` |
| TC-046 | Ticket lifecycle: validation, note, resolution required | Browser | `[TC-046]` |

Also covered by the Postman collection (39 requests, 120 assertions): status codes, error envelope with `request_id`, role checks, fault and ticket state transitions.

## Manual test procedures

Run these in the console against a running fleet. Clear all faults in Fault Lab before you start.

### TC-002 Duplicate messages are harmless
- **Role:** QA, then Support
- **Steps:** 1. Fault Lab: turn on Duplicate messages for MD-24012. 2. Wait 20 s. 3. Message log, filter serial MD-24012, status Duplicate. 4. Expand a row and copy its msg_id. 5. Filter by status Accepted and find the same msg_id.
- **Expected:** Each duplicate has exactly one Accepted twin with the same msg_id. Error text: "msg_id already processed". Battery and roll on the device page do not jump.

### TC-003 Corrupt payloads are rejected with a reason
- **Steps:** 1. Fault Lab: Corrupt payload on MD-24003. 2. Message log, status Invalid, serial MD-24003. 3. Expand a row.
- **Expected:** Each row shows a field-level error (e.g. `seq: Input should be a valid integer`) or "Malformed JSON", and the raw text is shown. Device state is unaffected.

### TC-007 Clock drift is detected
- **Steps:** 1. Fault Lab: Clock drift on MD-24011. 2. Open MD-24011.
- **Expected:** Within one heartbeat (about 10 s), "Clock vs cloud" shows +25 min and a medium Clock drift alert opens.

### TC-042 Remote resync against a faulty clock (manual variant)
- **Role:** QA (can command and inject)
- **Steps:** 1. With clock drift active, click Resync clock. 2. Commands tab. 3. Clear the fault in Fault Lab. 4. Resync again.
- **Expected:** First command: Failed, "RTC unstable: resync rejected (hardware clock fault)". Second: Completed, "clock corrected by -25 min"; the alert resolves itself on the next heartbeat.

### TC-044 Device offline and recovery
- **Steps:** 1. Fault Lab: Offline on MD-24013. 2. Wait 35 s. 3. Alerts. 4. Clear the fault. 5. Message log, flag Buffered, serial MD-24013.
- **Expected:** A medium Device offline alert appears after 15 fleet minutes. On reconnect, the events produced during the outage arrive flagged Buffered, the device returns Online, and the alert is auto-resolved ("Device reconnected").

### TC-010 Dispense failure is escalated
- **Steps:** 1. Fault Lab: Read error on a device whose next dose is soon (check its schedule against the fleet clock). 2. Wait for the dose time.
- **Expected:** One high-severity Dispense failed alert per due dose, with a 15-minute acknowledgement SLA. The dose shows Failed with reason "Read error".

### TC-016 Missed dose after the grace period
- **Steps:** 1. Fault Lab: No response on a device. 2. Note the next dose time. 3. Watch Alerts.
- **Expected:** No alert at due + 29 fleet minutes; a high Missed dose alert at due + 30.

### TC-020 Missed dose on an offline device
- **Steps:** 1. Turn on both Offline and No response for one device, before a dose is due. 2. Wait past due + 30.
- **Expected:** The Missed dose alert text says the device is offline, so the coordinator knows the dose may have been taken.

### TC-009 Late confirmation
- **Steps:** 1. Offline only (no "No response") on a device before a dose. 2. Wait until the Missed dose alert opens. 3. Clear Offline.
- **Expected:** The buffered dose_taken arrives, the dose becomes Late, and the missed-dose alert is auto-resolved.

### TC-011 Battery hysteresis
- **Steps:** 1. Fault Lab: Battery drain. 2. Wait for the battery to drop below 20 %. 3. Clear the fault.
- **Expected:** Battery low opens below 20 %. It stays open at 25 % and resolves itself at 30 % or more.

### TC-012 Roll change
- **Steps:** 1. Pick a device with 2 or fewer sachets (Devices list, Roll column). 2. Simulate roll change.
- **Expected:** The roll counter shows 28 of 28 after the next heartbeat; the Roll low alert resolves.

### TC-024 Login
- **Steps:** 1. Sign in with a wrong password. 2. Sign in with each demo account.
- **Expected:** Wrong password: "Invalid email or password." (no hint about which field). Each account lands on the Fleet overview with its role shown in the user menu.

### TC-025 / TC-040 Role boundaries
- **Steps:** Sign in as Care Coordinator. Visit `/messages` and `/fault-lab` directly.
- **Expected:** Both show "Access restricted". No Remote actions on device pages. Ticket status buttons are hidden for QA and Coordinator.

### TC-026 Alert workflow
- **Role:** Coordinator
- **Steps:** 1. Acknowledge an open alert. 2. Resolve with a note of fewer than 5 characters. 3. Resolve with a proper note.
- **Expected:** Step 2 is rejected with a validation message. After step 3, the alert moves to Resolved with your name and the note.

### TC-027 Overdue alerts
- **Steps:** Leave a high-severity alert (e.g. Missed dose) unacknowledged for more than 15 fleet minutes (30 s).
- **Expected:** It appears under the Past SLA view.

### TC-028 Duplicate command
- **Steps:** On an offline device, click Reboot twice.
- **Expected:** The second click is rejected: "A reboot command is already waiting for this device." The command later expires after 60 fleet minutes if the device stays offline.

### TC-029 / TC-045 Schedule editor
- **Role:** Support
- **Steps:** Enter `08:00, 25:00`, then `08:00, 08:00`, then `08:00, 13:00, 19:30`.
- **Expected:** Clear error for each invalid entry. Valid schedule saves and a Sync schedule command completes with "schedule 08:00, 13:00, 19:30".

### TC-033 Restart does not flag every message out of order
- **Steps:** 1. Restart the server. 2. Message log, flag Out of order.
- **Expected:** After the boot messages, new messages are in order. Before the fix, every heartbeat after a restart was flagged.

### TC-046 Ticket from a phone call
- **Role:** Support
- **Steps:** 1. New ticket: subject "Help", serial "24015". 2. Fix to a real subject, description and MD-24015. 3. Start investigating, add a note. 4. Resolve with an empty resolution, then with text.
- **Expected:** Field errors in step 1. Ticket SUP-xxxx created. Resolution required in step 4; afterwards Resolved with the resolution shown.

### Alert handover to support
- **Role:** Coordinator, then Support
- **Steps:** 1. On an open alert, choose Hand over to support. 2. Sign in as Support and open the ticket.
- **Expected:** The ticket is linked to the alert and device; the alert card shows its current status. Creating a ticket with an alert from one device and a serial from another is rejected (422).
