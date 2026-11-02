import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellOff } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, Pagination, PriorityBadge, StatusBadge, Table, TableSkeleton, Td, Th } from "@/components/common";
import { Button, Card, Dialog, Field, Input, Select, Textarea } from "@/components/ui";
import { ApiError, api, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { notifyError, notifyOk } from "@/lib/notify";
import { useSimClock } from "@/lib/sim";
import type { Alert } from "@/lib/types";
import { cn, humanize, simAgo } from "@/lib/utils";

const TYPES = ["missed_dose", "dispense_failed", "device_offline", "roll_empty", "roll_low", "clock_drift", "battery_low"];
const VIEWS = [
  { key: "open", label: "Open", query: { status: ["open"] } },
  { key: "overdue", label: "Past SLA", query: { overdue: true } },
  { key: "acknowledged", label: "Acknowledged", query: { status: ["acknowledged"] } },
  { key: "resolved", label: "Resolved", query: { status: ["resolved"] } },
];

function slaText(a: Alert, simNow?: string) {
  if (a.status !== "open" || !simNow) return null;
  const mins = Math.round((new Date(a.ack_due_at).getTime() - new Date(simNow).getTime()) / 60000);
  return mins >= 0 ? { text: `ack within ${mins} min`, late: false } : { text: `${-mins} min past SLA`, late: true };
}

export function ResolveDialog({ alert, onClose }: { alert: Alert | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [err, setErr] = useState<string>();
  const m = useMutation({
    mutationFn: () => api<Alert>(`/alerts/${alert!.id}/resolve`, { method: "POST", body: { resolution: text.trim() } }),
    onSuccess: (a) => { qc.invalidateQueries(); notifyOk(`${a.code} resolved`); setText(""); onClose(); },
    onError: (e) => (e instanceof ApiError && e.status === 422 ? setErr("Describe what you found and did (at least 5 characters).") : notifyError(e)),
  });
  return (
    <Dialog open={Boolean(alert)} onOpenChange={(o) => !o && onClose()} title={`Resolve ${alert?.code ?? ""}`}
      description={alert ? `${humanize(alert.type)} on ${alert.device.serial} (${alert.device.client_name}).` : undefined}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={m.isPending} onClick={() => {
        if (text.trim().length < 5) { setErr("Describe what you found and did (at least 5 characters)."); return; } m.mutate(); }}>Resolve alert</Button></>}>
      <Field label="Resolution" required error={err} hint="E.g. Called client: dose taken late, button needed a firmer press.">
        {(a) => <Textarea {...a} rows={3} value={text} onChange={(e) => { setText(e.target.value); setErr(undefined); }} />}
      </Field>
    </Dialog>
  );
}

export function TicketFromAlertDialog({ alert, onClose }: { alert: Alert | null; onClose: () => void }) {
  const nav = useNavigate();
  const { user } = useAuth();
  const [subject, setSubject] = useState("");
  const [desc, setDesc] = useState("");
  const [priority, setPriority] = useState("high");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => api<{ id: number; code: string }>("/tickets", { method: "POST", body: {
      subject: subject.trim() || `${humanize(alert!.type)} on ${alert!.device.serial}`, description: desc.trim() || alert!.message,
      reporter: user?.full_name ?? "Care coordination", priority, alert_id: alert!.id } }),
    onSuccess: (t) => { notifyOk(`${t.code} created`); onClose(); nav(`/tickets/${t.id}`); },
    onError: (e) => (e instanceof ApiError && e.status === 422 ? setErrors(e.fieldErrors()) : notifyError(e)),
  });
  if (!alert) return null;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} wide title="Hand over to support" description={`Creates a support ticket linked to ${alert.code} and ${alert.device.serial}.`}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={m.isPending} onClick={() => m.mutate()}>Create ticket</Button></>}>
      <div className="grid gap-4">
        <Field label="Subject" error={errors.subject}>{(a) => <Input {...a} placeholder={`${humanize(alert.type)} on ${alert.device.serial}`} value={subject} onChange={(e) => setSubject(e.target.value)} />}</Field>
        <Field label="What happened" error={errors.description} hint="Defaults to the alert text. Add what the client or caregiver told you.">
          {(a) => <Textarea {...a} rows={4} placeholder={alert.message} value={desc} onChange={(e) => setDesc(e.target.value)} />}</Field>
        <Field label="Priority">{(a) => <Select {...a} value={priority} onChange={(e) => setPriority(e.target.value)}>{["urgent", "high", "medium", "low"].map((p) => <option key={p} value={p}>{humanize(p)}</option>)}</Select>}</Field>
      </div>
    </Dialog>
  );
}

export default function AlertsPage() {
  const { can } = useAuth();
  const { now } = useSimClock();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const view = params.get("overdue") === "true" ? "overdue" : params.get("view") ?? "open";
  const type = params.get("type") ?? "";
  const [page, setPage] = useState(1);
  const [resolving, setResolving] = useState<Alert | null>(null);
  const [ticketing, setTicketing] = useState<Alert | null>(null);
  const v = VIEWS.find((x) => x.key === view) ?? VIEWS[0];
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["alerts", view, type, page], refetchInterval: 3000, placeholderData: (p) => p,
    queryFn: () => api<Page<Alert>>("/alerts", { query: { ...v.query, type, page, page_size: 20 } }),
  });
  const ack = useMutation({
    mutationFn: (id: number) => api<Alert>(`/alerts/${id}/acknowledge`, { method: "POST" }),
    onSuccess: (a) => { qc.invalidateQueries(); notifyOk(`${a.code} acknowledged`); },
    onError: (e) => notifyError(e),
  });
  const handle = can("alerts:handle");
  const set = (patch: Record<string, string>) => { const n = new URLSearchParams(params); n.delete("overdue"); Object.entries(patch).forEach(([k, x]) => (x ? n.set(k, x) : n.delete(k))); setParams(n, { replace: true }); setPage(1); };

  return (
    <>
      <PageHeader title="Alerts" description="Raised automatically from device messages and from silence. Highest severity and oldest first." />
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div role="tablist" className="flex rounded-md border border-line bg-card p-0.5">
          {VIEWS.map((x) => (
            <button key={x.key} role="tab" aria-selected={view === x.key} onClick={() => set({ view: x.key === "open" ? "" : x.key, ...(x.key === "overdue" ? { overdue: "true" } : {}) })}
              className={cn("rounded px-3 py-1.5 text-[13px] font-medium", view === x.key ? "bg-brand-600 text-white" : "text-ink-2 hover:bg-canvas")}>{x.label}</button>
          ))}
        </div>
        <Select aria-label="Alert type" value={type} onChange={(e) => set({ type: e.target.value })} className="w-auto">
          <option value="">All types</option>{TYPES.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}
        </Select>
      </div>
      <Card>
        {error ? <ErrorState error={error} onRetry={refetch} /> : (
          <>
            <Table>
              <thead><tr><Th>Alert</Th><Th>Severity</Th><Th>Device and client</Th><Th>What happened</Th><Th>Raised</Th><Th>Status</Th><Th className="text-right">Actions</Th></tr></thead>
              {isLoading ? <TableSkeleton cols={7} /> : (
                <tbody>
                  {data?.items.length === 0 && <tr><Td colSpan={7}><EmptyState icon={<BellOff className="size-6" />} title={view === "open" ? "No open alerts" : "Nothing here"} body={view === "open" ? "New alerts appear here within seconds." : undefined} /></Td></tr>}
                  {data?.items.map((a) => {
                    const sla = slaText(a, now);
                    return (
                      <tr key={a.id} data-testid={`alert-${a.code}`}>
                        <Td><span className="mono">{a.code}</span><span className="block text-[12.5px] font-medium">{humanize(a.type)}</span></Td>
                        <Td><PriorityBadge value={a.severity} /></Td>
                        <Td><Link to={`/devices/${a.device.serial}`} className="mono link">{a.device.serial}</Link>
                          <span className="block text-[12.5px] text-ink-2">{a.device.client_name}</span><span className="block text-[12px] text-ink-3">{a.device.care_team}</span></Td>
                        <Td className="max-w-[360px] text-[13px]">{a.message}{a.resolution && <span className="block text-[12.5px] text-ok-700 mt-1">{a.auto_resolved ? "Auto-resolved: " : "Resolved: "}{a.resolution}</span>}</Td>
                        <Td className="whitespace-nowrap text-[12.5px] text-ink-2">{simAgo(a.created_at, now)}{sla && <span className={cn("block font-medium", sla.late ? "text-bad-700" : "text-ink-3")}>{sla.text}</span>}</Td>
                        <Td><StatusBadge status={a.status} />{a.acknowledged_by && <span className="block text-[12px] text-ink-3 mt-0.5">by {a.acknowledged_by}</span>}</Td>
                        <Td className="text-right whitespace-nowrap space-x-1.5">
                          {handle && a.status === "open" && <Button size="sm" loading={ack.isPending && ack.variables === a.id} onClick={() => ack.mutate(a.id)}>Acknowledge</Button>}
                          {handle && a.status !== "resolved" && <Button size="sm" variant="secondary" onClick={() => setResolving(a)}>Resolve</Button>}
                          {can("tickets:create") && a.status !== "resolved" && <Button size="sm" variant="ghost" onClick={() => setTicketing(a)}>Ticket</Button>}
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              )}
            </Table>
            {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
      <ResolveDialog alert={resolving} onClose={() => setResolving(null)} />
      <TicketFromAlertDialog alert={ticketing} onClose={() => setTicketing(null)} />
    </>
  );
}
