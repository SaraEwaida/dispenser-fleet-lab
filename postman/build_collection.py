"""Generates Dispenser-Fleet-Lab.postman_collection.json and local.postman_environment.json.

Run: python3 postman/build_collection.py
"""
import json, os, uuid
HERE = os.path.dirname(os.path.abspath(__file__))


def t(*lines): return [{"listen": "test", "script": {"type": "text/javascript", "exec": list(lines)}}]


def req(name, method, path, body=None, token="{{support_token}}", tests=()):
    h = [{"key": "Content-Type", "value": "application/json"}] if body is not None else []
    if token: h.append({"key": "Authorization", "value": f"Bearer {token}"})
    path_part, _, query = path.partition("?")
    url = {"raw": "{{baseUrl}}/api/v1" + path, "host": ["{{baseUrl}}"], "path": ["api", "v1"] + [p for p in path_part.split("/") if p]}
    if query: url["query"] = [{"key": kv.split("=")[0], "value": kv.split("=", 1)[1]} for kv in query.split("&")]
    item = {"name": name, "request": {"method": method, "header": h, "url": url}, "event": t(*tests)}
    if body is not None: item["request"]["body"] = {"mode": "raw", "raw": json.dumps(body, indent=2)}
    return item


COMMON = ['pm.test("has X-Request-ID header", () => pm.response.to.have.header("X-Request-ID"));',
          'pm.test("responds in under 1500 ms", () => pm.expect(pm.response.responseTime).to.be.below(1500));']
ERR = ['pm.test("error envelope with request_id", () => { const e = pm.response.json().error; pm.expect(e).to.include.keys("code","message","request_id"); pm.expect(e.request_id).to.eql(pm.response.headers.get("X-Request-ID")); });']
def status(code): return f'pm.test("{code}", () => pm.response.to.have.status({code}));'


def login(email, var):
    return req(f"Login as {email.split('@')[0]}", "POST", "/auth/login", {"email": email, "password": "{{demo_password}}"}, token=None, tests=[
        status(200), 'const b = pm.response.json();',
        'pm.test("returns bearer token", () => { pm.expect(b.token_type).to.eql("bearer"); pm.expect(b.access_token).to.be.a("string"); });',
        f'pm.collectionVariables.set("{var}", b.access_token);', *COMMON])


folders = [
    {"name": "1. Auth & system", "item": [
        req("Health check", "GET", "/health", token=None, tests=[status(200), 'const b = pm.response.json();',
            'pm.test("database ok", () => pm.expect(b.database).to.eql("ok"));', *COMMON]),
        login("coordinator@fleet.example.com", "coordinator_token"), login("support@fleet.example.com", "support_token"),
        login("qa@fleet.example.com", "qa_token"),
        req("Wrong password → 401", "POST", "/auth/login", {"email": "support@fleet.example.com", "password": "wrong"}, token=None,
            tests=[status(401), 'pm.test("generic message", () => pm.expect(pm.response.json().error.message).to.eql("Invalid email or password."));', *ERR]),
        req("No token → 401", "GET", "/devices", token=None, tests=[status(401), *ERR]),
        req("Simulated clock", "GET", "/sim", tests=[status(200), 'pm.test("fleet speed reported", () => pm.expect(pm.response.json().speed).to.be.above(0));', *COMMON]),
    ]},
    {"name": "2. Fleet & devices", "item": [
        req("Fleet summary", "GET", "/fleet/summary", tests=[status(200), 'const b = pm.response.json();',
            'pm.test("has devices and alerts blocks", () => pm.expect(b).to.include.keys("devices","alerts","adherence_24h"));', *COMMON]),
        req("List devices (search)", "GET", "/devices?q=MD-2401&page_size=5", tests=[status(200), 'const b = pm.response.json();',
            'pm.test("paginated envelope", () => pm.expect(b).to.have.keys("items","total","page","page_size"));',
            'pm.test("every serial matches", () => b.items.forEach(d => pm.expect(d.serial).to.include("MD-2401")));', *COMMON]),
        req("Device detail", "GET", "/devices/MD-24020", tests=[status(200), 'const b = pm.response.json();',
            'pm.test("serial and schedule", () => { pm.expect(b.serial).to.eql("MD-24020"); pm.expect(b.schedule).to.be.an("array").that.is.not.empty; });', *COMMON]),
        req("Unknown device → 404", "GET", "/devices/MD-99999", tests=[status(404), *ERR]),
        req("Device message log", "GET", "/devices/MD-24020/messages?page_size=5", tests=[status(200),
            'pm.test("messages belong to device", () => pm.response.json().items.forEach(m => pm.expect(m.serial).to.eql("MD-24020")));', *COMMON]),
        req("Invalid schedule time → 422", "PUT", "/devices/MD-24020/schedule", {"times": ["08:00", "25:00"]},
            tests=[status(422), *ERR]),
        req("Coordinator cannot send commands → 403", "POST", "/devices/MD-24020/commands", {"type": "reboot"}, token="{{coordinator_token}}",
            tests=[status(403), *ERR]),
        req("Unknown command type → 422", "POST", "/devices/MD-24020/commands", {"type": "self_destruct"}, tests=[status(422), *ERR]),
        req("Send resync_clock", "POST", "/devices/MD-24020/commands", {"type": "resync_clock"}, tests=[
            'pm.test("201 or 409 if one is already pending", () => pm.expect(pm.response.code).to.be.oneOf([201, 409]));', *COMMON]),
    ]},
    {"name": "3. Fault Lab", "item": [
        req("Fault catalog", "GET", "/faults", token="{{qa_token}}", tests=[status(200),
            'pm.test("7 fault types", () => pm.expect(pm.response.json().catalog.length).to.eql(7));', *COMMON]),
        req("Clear all faults", "DELETE", "/faults", token="{{qa_token}}", tests=[status(200), *COMMON]),
        req("Support cannot inject faults → 403", "POST", "/devices/MD-24021/faults", {"type": "battery_drain"}, tests=[status(403), *ERR]),
        req("Inject battery_drain", "POST", "/devices/MD-24021/faults", {"type": "battery_drain"}, token="{{qa_token}}",
            tests=[status(201), 'pm.test("describes the fault", () => pm.expect(pm.response.json().description).to.be.a("string"));', *COMMON]),
        req("Same fault twice → 409", "POST", "/devices/MD-24021/faults", {"type": "battery_drain"}, token="{{qa_token}}",
            tests=[status(409), 'pm.test("FAULT_ACTIVE", () => pm.expect(pm.response.json().error.code).to.eql("FAULT_ACTIVE"));', *ERR]),
        req("Unknown fault type → 422", "POST", "/devices/MD-24021/faults", {"type": "meltdown"}, token="{{qa_token}}", tests=[status(422), *ERR]),
        req("Clear battery_drain", "DELETE", "/devices/MD-24021/faults/battery_drain", token="{{qa_token}}", tests=[status(204)]),
        req("Clear it again → 404", "DELETE", "/devices/MD-24021/faults/battery_drain", token="{{qa_token}}", tests=[status(404), *ERR]),
    ]},
    {"name": "4. Alerts & telemetry", "item": [
        req("Open alerts", "GET", "/alerts?status=open&page_size=10", tests=[status(200),
            'pm.test("only open alerts", () => pm.response.json().items.forEach(a => pm.expect(a.status).to.eql("open")));', *COMMON]),
        req("Resolve unknown alert → 404", "POST", "/alerts/999999/resolve", {"resolution": "Checked with caregiver."}, tests=[status(404), *ERR]),
        req("Rejected messages (invalid)", "GET", "/messages?status=invalid&page_size=5", tests=[status(200),
            'pm.test("each carries an error", () => pm.response.json().items.forEach(m => pm.expect(m.error).to.be.a("string")));', *COMMON]),
        req("Duplicate messages", "GET", "/messages?status=duplicate&page_size=5", tests=[status(200), *COMMON]),
        req("Coordinator cannot read raw telemetry → 403", "GET", "/messages", token="{{coordinator_token}}", tests=[status(403), *ERR]),
        req("Audit log", "GET", "/audit?page_size=5", tests=[status(200), *COMMON]),
    ]},
    {"name": "5. Support tickets", "item": [
        req("Ticket validation → 422", "POST", "/tickets", {"subject": "Hi", "description": "short", "reporter": "C"},
            tests=[status(422), 'const f = pm.response.json().error.details.map(d => d.field);',
                   'pm.test("lists subject and description", () => { pm.expect(f).to.include("subject"); pm.expect(f).to.include("description"); });', *ERR]),
        req("Unknown device on ticket → 422", "POST", "/tickets", {"subject": "Dispenser silent", "description": "No reminders since this morning.", "reporter": "Caregiver", "device_serial": "MD-99999"},
            tests=[status(422), *ERR]),
        req("Create ticket", "POST", "/tickets", {"subject": "Dispenser silent since morning", "description": "Caregiver reports no reminder at 08:00 or 13:00.", "reporter": "Caregiver (Postman)", "priority": "high", "device_serial": "MD-24022"},
            tests=[status(201), 'const b = pm.response.json();', 'pm.test("ticket code format", () => pm.expect(b.code).to.match(/^SUP-\\d+$/));',
                   'pm.test("starts open", () => pm.expect(b.status).to.eql("open"));', 'pm.collectionVariables.set("ticket_id", b.id);', *COMMON]),
        req("Invalid transition open → open → 409", "POST", "/tickets/{{ticket_id}}/status", {"status": "open"},
            tests=[status(409), 'pm.test("INVALID_TRANSITION", () => pm.expect(pm.response.json().error.code).to.eql("INVALID_TRANSITION"));', *ERR]),
        req("Start investigating", "POST", "/tickets/{{ticket_id}}/status", {"status": "investigating"}, tests=[status(200), *COMMON]),
        req("Add investigation note", "POST", "/tickets/{{ticket_id}}/notes", {"body": "Message log shows no heartbeats since 07:40. Device offline."},
            tests=[status(201), 'pm.test("note stored", () => pm.expect(pm.response.json().notes.length).to.eql(1));', *COMMON]),
        req("Resolve without resolution → 422", "POST", "/tickets/{{ticket_id}}/status", {"status": "resolved"}, tests=[status(422), *ERR]),
        req("Resolve", "POST", "/tickets/{{ticket_id}}/status", {"status": "resolved", "resolution": "Router was off. Caregiver restarted it; device reconnected and buffered events arrived."},
            tests=[status(200), 'pm.test("resolution saved", () => pm.expect(pm.response.json().resolution).to.include("Router"));', *COMMON]),
        req("QA cannot manage tickets → 403", "POST", "/tickets/{{ticket_id}}/status", {"status": "investigating"}, token="{{qa_token}}", tests=[status(403), *ERR]),
    ]},
]

collection = {
    "info": {"_postman_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "dispenser-fleet-lab")), "name": "Dispenser Fleet Lab API",
             "description": "Requests and assertions for the Dispenser Fleet Lab REST API. Run the folders in order (login sets the tokens).",
             "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "item": folders,
    "variable": [{"key": k, "value": ""} for k in ("coordinator_token", "support_token", "qa_token", "ticket_id")],
}
env = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "dispenser-fleet-lab-env")), "name": "Dispenser Fleet Lab (local)",
       "values": [{"key": "baseUrl", "value": "http://localhost:8000", "enabled": True},
                  {"key": "demo_password", "value": "Demo@2026!", "enabled": True}]}
json.dump(collection, open(os.path.join(HERE, "Dispenser-Fleet-Lab.postman_collection.json"), "w"), indent=2)
json.dump(env, open(os.path.join(HERE, "local.postman_environment.json"), "w"), indent=2)
print(sum(len(f["item"]) for f in folders), "requests")
