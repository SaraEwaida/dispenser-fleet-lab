import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BatteryMedium, Clock, Package, Signal } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, PriorityBadge, StatusBadge, Table, Td, Th } from "@/components/common";
import { Button, Card, CardHeader, Dialog, Field, Input, Spinner, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { ApiError, api, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { notifyError, notifyOk } from "@/lib/notify";
import { useSimClock } from "@/lib/sim";
import type { DeviceDetail as D, Message } from "@/lib/types";
import { cn, hhmm, humanize, simAgo } from "@/lib/utils";
import { MessageRow } from "./MessagesPage";

const COMMANDS = [
  { type: "resync_clock", label: "Resync clock", help: "Set the device clock to cloud time." },
  { type: "sync_schedule", label: "Sync schedule", help: "Re-send the dose schedule to the device." },
  { type: "reboot", label: "Reboot", help: "Restart the dispenser remotely." },
  { type: "replace_roll", label: "Simulate roll change", help: "Simulates a caregiver loading a new 28-sachet roll." },
];

function Vital({ icon, label, value, bad }: { icon: React.ReactNode; label: string; value: string; bad?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <span className={cn("grid size-9 place-items-center rounded-md bg-canvas text-ink-2 [&_svg]:size-[18px]", bad && "bg-bad-50 text-bad-700")}>{icon}</span>
      <span><span className="block text-[12px] text-ink-3">{label}</span><span className={cn("block font-medium tabular-nums", bad && "text-bad-700")}>{value}</span></span>
    </div>
  );
}

function ScheduleDialog({ device, onClose }: { device: D; onClose: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState(device.schedule.join(", "));
  const [err, setErr] = useState<string>();
  const m = useMutation({
    mutationFn: (times: string[]) => api(`/devices/${device.serial}/schedule`, { method: "PUT", body: { times } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["device", device.serial] }); notifyOk("Schedule saved", "A sync command was queued for the device."); onClose(); },
    onError: (e) => (e instanceof ApiError && e.status === 422 ? setErr(e.details[0]?.issue ?? e.message) : notifyError(e)),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={`Dose schedule for ${device.serial}`} description={`Times in the client's timezone (${device.client.timezone}).`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={m.isPending} onClick={() => {
        const times = text.split(/[,\s]+/).map((t) => t.trim()).filter(Boolean);
        if (!times.length) { setErr("Enter at least one time."); return; }
        const bad = times.find((t) => !/^([01]\d|2[0-3]):[0-5]\d$/.test(t));
        if (bad) { setErr(`'${bad}' is not a valid time. Use HH:MM, 24-hour.`); return; }
        if (new Set(times).size !== times.length) { setErr("Times must be unique."); return; }
        if (times.length > 6) { setErr("At most 6 dose times per day."); return; }
        m.mutate(times);
      }}>Save schedule</Button></>}>
      <Field label="Dose times" error={err} hint="Comma-separated, e.g. 08:00, 12:30, 18:00">{(a) => <Input {...a} className="font-mono" value={text} onChange={(e) => { setText(e.target.value); setErr(undefined); }} />}</Field>
    </Dialog>
  );
}

export default function DeviceDetail() {
  const { serial = "" } = useParams();
  const { can } = useAuth();
  const { now } = useSimClock();
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const q = useQuery({ queryKey: ["device", serial], refetchInterval: 3000, queryFn: () => api<D>(`/devices/${serial}`) });
  const msgs = useQuery({ queryKey: ["device", serial, "messages"], enabled: can("telemetry:read"), refetchInterval: 3000,
    queryFn: () => api<Page<Message>>(`/devices/${serial}/messages`, { query: { page_size: 40 } }) });
  const send = useMutation({
    mutationFn: (type: string) => api<{ note: string | null }>(`/devices/${serial}/commands`, { method: "POST", body: { type } }),
    onSuccess: (r, type) => { qc.invalidateQueries({ queryKey: ["device", serial] }); notifyOk(`${humanize(type)} queued`, r.note ?? "It will be delivered within a second."); },
    onError: (e) => notifyError(e),
  });

  if (q.isLoading) return <Spinner label="Loading device" />;
  if (q.error || !q.data) return <div className="card"><ErrorState error={q.error} onRetry={q.refetch} /></div>;
  const d = q.data;
  const drift = d.clock_offset_s === null ? "—" : Math.abs(d.clock_offset_s) < 60 ? "In sync" : `${d.clock_offset_s > 0 ? "+" : ""}${Math.round(d.clock_offset_s / 60)} min`;

  return (
    <>
      <PageHeader back={{ to: "/devices", label: "Devices" }}
        title={<span className="flex flex-wrap items-center gap-3"><span className="font-mono">{d.serial}</span><StatusBadge status={d.status} /></span>}
        description={<span>{d.client.name} · <span className="mono">{d.client.code}</span> · {d.client.care_team} · local time {d.local_time}</span>} />
      {d.faults.length > 0 && (
        <p className="mb-4 rounded-md border border-brand-600/30 bg-brand-50 px-4 py-2.5 text-[13px] text-brand-700">
          Injected fault active: <strong>{d.faults.map(humanize).join(", ")}</strong>. This device is part of a Fault Lab exercise.
        </p>
      )}
      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="p-5 grid grid-cols-2 gap-5 content-start">
          <Vital icon={<Signal />} label="Last message" value={simAgo(d.last_seen_at, now)} bad={d.status === "offline"} />
          <Vital icon={<BatteryMedium />} label="Backup battery" value={d.battery_pct === null ? "—" : `${d.battery_pct}%`} bad={d.battery_pct !== null && d.battery_pct < 20} />
          <Vital icon={<Package />} label="Medication roll" value={`${d.roll_remaining ?? "—"} of ${d.roll_capacity}`} bad={d.roll_remaining !== null && d.roll_remaining <= 2} />
          <Vital icon={<Clock />} label="Clock vs cloud" value={drift} bad={d.clock_offset_s !== null && Math.abs(d.clock_offset_s) > 300} />
          <div className="col-span-2 text-[13px] text-ink-2 flex flex-wrap gap-x-4 gap-y-1">
            <span>Firmware <span className="mono">{d.firmware}</span></span><span>Signal {d.rssi_dbm ?? "—"} dBm</span>
            <span>Adherence 24 h {d.adherence_24h === null ? "—" : `${d.adherence_24h}%`}</span>
          </div>
          <div className="col-span-2 border-t border-line pt-4">
            <div className="flex items-center justify-between"><p className="text-[13px] font-medium">Dose schedule</p>
              {can("devices:schedule") && <Button size="sm" variant="link" onClick={() => setEditing(true)}>Edit</Button>}</div>
            <p className="mono mt-1">{d.schedule.join("  ·  ")}</p>
          </div>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader title="Open alerts" description={d.alerts.length ? undefined : "Nothing needs attention on this device."}
            action={<Link className="link text-[13px]" to={`/alerts?view=resolved`}>History</Link>} />
          {d.alerts.length > 0 && (
            <ul className="px-5 pb-4 space-y-2">
              {d.alerts.map((a) => (
                <li key={a.id} className="flex items-start gap-3 rounded-md border border-line px-3 py-2">
                  <PriorityBadge value={a.severity} />
                  <div className="flex-1 min-w-0"><p className="text-[13.5px] font-medium">{humanize(a.type)} <span className="mono text-ink-3 font-normal">{a.code}</span></p>
                    <p className="text-[12.5px] text-ink-2">{a.message}</p></div>
                  <StatusBadge status={a.status} />
                </li>
              ))}
            </ul>
          )}
          {can("devices:command") && (
            <div className="border-t border-line px-5 py-4">
              <p className="text-[13px] font-medium mb-2">Remote actions</p>
              <div className="flex flex-wrap gap-2">
                {COMMANDS.map((c) => <Button key={c.type} size="sm" variant="secondary" title={c.help} loading={send.isPending && send.variables === c.type} onClick={() => send.mutate(c.type)}>{c.label}</Button>)}
              </div>
              {d.status !== "online" && <p className="text-[12.5px] text-warn-700 mt-2">The device is not online. Commands wait in the queue and expire after 60 fleet minutes.</p>}
            </div>
          )}
        </Card>
      </div>

      <Tabs defaultValue="doses" className="mt-4">
        <TabsList className="mb-3">
          <TabsTrigger value="doses">Doses (48 h)</TabsTrigger>
          <TabsTrigger value="commands">Commands</TabsTrigger>
          {can("telemetry:read") && <TabsTrigger value="messages">Messages</TabsTrigger>}
        </TabsList>
        <TabsContent value="doses"><Card>
          {d.doses.length === 0 ? <EmptyState title="No doses due yet" body="Doses appear once fleet time passes a scheduled time." /> : (
            <Table><thead><tr><Th>Due (local)</Th><Th>Outcome</Th><Th>Pressed (device time)</Th><Th>Confirmed (cloud)</Th><Th>Note</Th></tr></thead>
              <tbody>{d.doses.map((x) => (
                <tr key={x.id}><Td className="font-medium">{x.due_local}</Td><Td><StatusBadge status={x.status} /></Td>
                  <Td className="text-ink-2">{hhmm(x.taken_at)}</Td><Td className="text-ink-2">{hhmm(x.confirmed_at)}</Td>
                  <Td className="text-[12.5px] text-ink-3">{x.failure_reason ? humanize(x.failure_reason) : x.status === "late" ? "Confirmed after it was escalated" : ""}</Td></tr>))}</tbody></Table>
          )}</Card></TabsContent>
        <TabsContent value="commands"><Card>
          {d.commands.length === 0 ? <EmptyState title="No commands sent" /> : (
            <Table><thead><tr><Th>Command</Th><Th>Status</Th><Th>Created</Th><Th>Completed</Th><Th>Device response</Th></tr></thead>
              <tbody>{d.commands.map((c) => (
                <tr key={c.id} data-testid={`command-${c.type}`}><Td className="font-medium">{humanize(c.type)}</Td><Td><StatusBadge status={c.status} /></Td>
                  <Td className="text-ink-2">{hhmm(c.created_at)}</Td><Td className="text-ink-2">{hhmm(c.completed_at)}</Td>
                  <Td className={cn("text-[13px]", c.status === "failed" && "text-bad-700")}>{c.result ?? "—"}</Td></tr>))}</tbody></Table>
          )}</Card></TabsContent>
        {can("telemetry:read") && <TabsContent value="messages"><Card>
          <ul>{msgs.data?.items.map((m) => <MessageRow key={m.id} m={m} />)}</ul>
          {msgs.data?.items.length === 0 && <EmptyState title="No messages yet" />}
        </Card></TabsContent>}
      </Tabs>
      {editing && <ScheduleDialog device={d} onClose={() => setEditing(false)} />}
    </>
  );
}
