import { useMutation, useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, Pagination, PriorityBadge, SearchBox, StatusBadge, Table, TableSkeleton, Td, Th, useDebounced } from "@/components/common";
import { Button, Card, Dialog, Field, Input, Select, Textarea } from "@/components/ui";
import { ApiError, api, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { notifyError, notifyOk } from "@/lib/notify";
import type { Ticket } from "@/lib/types";
import { fmtDateTime, humanize, timeAgo } from "@/lib/utils";

const STATUSES = ["open", "investigating", "escalated", "resolved"];

function NewTicketDialog({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const { user } = useAuth();
  const [f, setF] = useState({ subject: "", description: "", reporter: "", priority: "medium", device_serial: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => { setF({ ...f, [k]: e.target.value }); setErrors({ ...errors, [k]: "" }); };
  const m = useMutation({
    mutationFn: () => api<Ticket>("/tickets", { method: "POST", body: { ...f, reporter: f.reporter.trim() || user?.full_name, device_serial: f.device_serial.trim().toUpperCase() || null } }),
    onSuccess: (t) => { notifyOk(`${t.code} created`); onClose(); nav(`/tickets/${t.id}`); },
    onError: (e) => (e instanceof ApiError && e.status === 422 ? setErrors(e.fieldErrors()) : notifyError(e)),
  });
  const submit = () => {
    const e: Record<string, string> = {};
    if (f.subject.trim().length < 5) e.subject = "At least 5 characters.";
    if (f.description.trim().length < 10) e.description = "Describe the problem in at least 10 characters.";
    if (f.device_serial.trim() && !/^MD-\d{5}$/i.test(f.device_serial.trim())) e.device_serial = "Serial looks like MD-24001.";
    setErrors(e);
    if (!Object.keys(e).length) m.mutate();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} wide title="New support ticket" description="Log a call or message from a client, caregiver or pharmacy."
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={m.isPending} onClick={submit}>Create ticket</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field className="sm:col-span-2" label="Subject" required error={errors.subject}>{(a) => <Input {...a} value={f.subject} onChange={set("subject")} placeholder="Dispenser beeps but nothing comes out" />}</Field>
        <Field className="sm:col-span-2" label="Description" required error={errors.description}>{(a) => <Textarea {...a} rows={4} value={f.description} onChange={set("description")} placeholder="What the caller reported, when it started, what they already tried." />}</Field>
        <Field label="Reported by" hint={`Defaults to ${user?.full_name}`} error={errors.reporter}>{(a) => <Input {...a} value={f.reporter} onChange={set("reporter")} placeholder="Caregiver, pharmacy, client" />}</Field>
        <Field label="Device serial" error={errors.device_serial} hint="Optional">{(a) => <Input {...a} className="font-mono" value={f.device_serial} onChange={set("device_serial")} placeholder="MD-24001" />}</Field>
        <Field label="Priority">{(a) => <Select {...a} value={f.priority} onChange={set("priority")}>{["urgent", "high", "medium", "low"].map((p) => <option key={p} value={p}>{humanize(p)}</option>)}</Select>}</Field>
      </div>
    </Dialog>
  );
}

export default function TicketsPage() {
  const nav = useNavigate();
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const [status, setStatus] = useState("active");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const statusQuery = status === "active" ? ["open", "investigating", "escalated"] : status ? [status] : undefined;
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["tickets", dq, status, page], refetchInterval: 10000, placeholderData: (p) => p,
    queryFn: () => api<Page<Ticket>>("/tickets", { query: { q: dq, status: statusQuery, page, page_size: 25 } }),
  });
  return (
    <>
      <PageHeader title="Support tickets" description="Calls and messages from clients, caregivers and pharmacies, and alerts handed over by care coordination."
        actions={can("tickets:create") && <Button onClick={() => setCreating(true)}><Plus />New ticket</Button>} />
      <Card>
        <div className="flex flex-wrap gap-3 p-4">
          <SearchBox className="flex-1 min-w-[220px]" label="Search tickets" placeholder="Code, subject, serial or reporter" value={q} onChange={(v) => { setQ(v); setPage(1); }} />
          <Select aria-label="Status" className="w-auto" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="active">Active</option><option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
        </div>
        {error ? <ErrorState error={error} onRetry={refetch} /> : (
          <>
            <Table>
              <thead><tr><Th>Ticket</Th><Th>Subject</Th><Th>Device</Th><Th>Priority</Th><Th>Status</Th><Th>Reporter</Th><Th>Updated</Th></tr></thead>
              {isLoading ? <TableSkeleton cols={7} /> : (
                <tbody>
                  {data?.items.length === 0 && <tr><Td colSpan={7}><EmptyState title="No tickets" body={status === "active" ? "Nothing is waiting for support." : "No tickets match these filters."} /></Td></tr>}
                  {data?.items.map((t) => (
                    <tr key={t.id} data-testid={`ticket-${t.code}`} className="hover:bg-canvas/60 cursor-pointer" onClick={() => nav(`/tickets/${t.id}`)}>
                      <Td className="mono font-medium whitespace-nowrap">{t.code}</Td>
                      <Td className="max-w-[360px]"><span className="line-clamp-1">{t.subject}</span>{t.alert_id && <span className="text-[12px] text-ink-3">From an alert</span>}</Td>
                      <Td className="mono">{t.device_serial ?? "—"}</Td>
                      <Td><PriorityBadge value={t.priority} /></Td>
                      <Td><StatusBadge status={t.status} /></Td>
                      <Td className="text-ink-2">{t.reporter}</Td>
                      <Td className="text-ink-2 whitespace-nowrap text-[13px]"><span title={fmtDateTime(t.updated_at)}>{timeAgo(t.updated_at)}</span></Td>
                    </tr>
                  ))}
                </tbody>
              )}
            </Table>
            {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
      {creating && <NewTicketDialog onClose={() => setCreating(false)} />}
    </>
  );
}
