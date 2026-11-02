import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/common";
import { Card } from "@/components/ui";
import { cn } from "@/lib/utils";

type Playbook = { id: string; title: string; alert: string; severity: string; when: string; check: string[]; act: string[]; escalate: string };

const PLAYBOOKS: Playbook[] = [
  { id: "offline", title: "Device offline", alert: "device_offline", severity: "Medium",
    when: "No message from the device for 15 minutes (three missed heartbeats).",
    check: ["Open the device page. Note the time of the last message and the battery level before it went quiet.",
      "Check the message log for the serial: did it send a boot message or a low battery just before?",
      "Check other devices from the same care team. Several offline at once points at the network, not the device."],
    act: ["Call the client or caregiver: is the dispenser plugged in, is the screen on, has the home Wi-Fi or mobile signal changed?",
      "Ask them to unplug and re-plug the dispenser. Do not ask them to open it.",
      "When it reconnects, buffered events arrive flagged Buffered. Confirm dose events from the outage were delivered."],
    escalate: "Still offline after a power cycle and a confirmed working connection: escalate with the serial, last-seen time and what the caller tried." },
  { id: "missed", title: "Missed dose", alert: "missed_dose", severity: "High",
    when: "A dose was due and the button was not pressed within 30 minutes.",
    check: ["Is the device online? If it is offline, the dose may have been taken; wait for buffered events before calling.",
      "Look at the dose history: one missed dose or a pattern?"],
    act: ["Care coordination calls the client or their caregiver to check in.",
      "If the client confirms they took it, the alert is resolved with a note. A late confirmation from the device resolves it automatically.",
      "Repeated misses: raise with the care team, it is not a device problem."],
    escalate: "Device shows the button was pressed but the cloud recorded a miss: that is a defect. Escalate with the msg_id from the message log." },
  { id: "dispense", title: "Dispense failed", alert: "dispense_failed", severity: "High",
    when: "The client pressed the button but the device could not dispense (unreadable sachet, jam or empty roll).",
    check: ["Open the alert: the reason is in the message (read_error, jam, roll_empty).",
      "Check the roll counter on the device page."],
    act: ["The client did not get the medication. Care coordination calls right away.",
      "Roll empty: arrange a roll change with the pharmacy. Jam or read error: ask the caregiver to reseat the roll.",
      "After a reseat, ask the client to press again and confirm a dose_taken message arrives."],
    escalate: "Read errors on a fresh roll, or more than two failures in a day: escalate to engineering with the serial and failure times." },
  { id: "drift", title: "Clock drift", alert: "clock_drift", severity: "Medium",
    when: "The device clock differs from cloud time by more than 5 minutes. Reminders will sound at the wrong time.",
    check: ["Device page: clock vs cloud shows the offset.", "Commands tab: has a resync already been tried?"],
    act: ["Send Resync clock from the device page.", "Watch the command: Completed means the alert resolves on the next heartbeat."],
    escalate: "Resync fails with an RTC error: the hardware clock is faulty. Escalate for a device swap; do not keep resending." },
  { id: "battery", title: "Battery low", alert: "battery_low", severity: "Low",
    when: "Backup battery below 20 %. The device is probably unplugged.",
    check: ["Check the battery trend in the message log heartbeats."],
    act: ["Ask the caregiver to plug the dispenser in. The alert resolves on its own once the battery reaches 30 %."],
    escalate: "Battery keeps falling while the caller confirms it is plugged in: escalate, the power supply may be faulty." },
  { id: "roll", title: "Roll running out", alert: "roll_low / roll_empty", severity: "Medium (empty: High)",
    when: "Two or fewer sachets left on the roll.",
    check: ["Check the dose schedule: how many hours until the roll is empty?"],
    act: ["Confirm the pharmacy has the next roll scheduled.", "After the caregiver loads a new roll, the counter resets and the alert resolves."],
    escalate: "Counter does not reset after a roll change: escalate with the serial." },
  { id: "messages", title: "Duplicate or invalid messages", alert: "message log", severity: "Info",
    when: "The message log shows Duplicate or Invalid rows for a device.",
    check: ["Duplicates share a msg_id with an accepted message. They are expected after network retries and are ignored safely.",
      "Invalid rows carry a field-level error. One-offs are noise; a steady stream is not."],
    act: ["No action for the client. Note the pattern on the ticket if one exists."],
    escalate: "Many invalid messages from one device, or a duplicate that changed a dose count: escalate with example msg_ids." },
];

export default function Playbooks() {
  const [sel, setSel] = useState(PLAYBOOKS[0].id);
  const p = PLAYBOOKS.find((x) => x.id === sel)!;
  return (
    <>
      <PageHeader title="L1 playbooks" description="What to check, what to do and when to escalate, for every alert the fleet can raise." />
      <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
        <Card className="p-2 h-fit">
          <nav aria-label="Playbooks" className="flex lg:flex-col gap-1 overflow-x-auto">
            {PLAYBOOKS.map((x) => (
              <button key={x.id} onClick={() => setSel(x.id)} aria-current={sel === x.id}
                className={cn("text-left rounded-md px-3 py-2 text-[13.5px] whitespace-nowrap", sel === x.id ? "bg-brand-50 text-brand-700 font-medium" : "hover:bg-canvas text-ink-2")}>{x.title}</button>
            ))}
          </nav>
        </Card>
        <Card className="p-6 space-y-5">
          <div>
            <h2 className="text-lg font-semibold">{p.title}</h2>
            <p className="text-[13px] text-ink-3 mt-0.5">Alert <span className="mono">{p.alert}</span> · Severity {p.severity}</p>
            <p className="mt-2">{p.when}</p>
          </div>
          <section><h3 className="font-medium mb-1.5">1. Check</h3><ul className="list-disc pl-5 space-y-1 text-[14px] text-ink-2">{p.check.map((s) => <li key={s}>{s}</li>)}</ul></section>
          <section><h3 className="font-medium mb-1.5">2. Act</h3><ul className="list-disc pl-5 space-y-1 text-[14px] text-ink-2">{p.act.map((s) => <li key={s}>{s}</li>)}</ul></section>
          <section className="rounded-md border border-warn-600/30 bg-warn-50 px-4 py-3"><h3 className="font-medium mb-1 text-warn-700">3. Escalate when</h3><p className="text-[14px]">{p.escalate}</p></section>
          <p className="text-[13px] text-ink-3">Related: <Link className="link" to={`/alerts?view=open`}>open alerts</Link> · <Link className="link" to="/tickets">tickets</Link></p>
        </Card>
      </div>
    </>
  );
}
