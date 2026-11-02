import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ErrorState, KV, PageHeader, PriorityBadge, StatusBadge } from "@/components/common";
import { Button, Card, CardHeader, Dialog, Field, Spinner, Textarea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { notifyError, notifyOk } from "@/lib/notify";
import type { Alert, Ticket } from "@/lib/types";
import { fmtDateTime, humanize } from "@/lib/utils";

const NEXT: Record<string, string[]> = {
  open: ["investigating", "escalated", "resolved"], investigating: ["escalated", "resolved"],
  escalated: ["investigating", "resolved"], resolved: ["investigating"],
};
const ACTION_LABEL: Record<string, string> = { investigating: "Start investigating", escalated: "Escalate to engineering", resolved: "Resolve" };

export default function TicketDetail() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [resolving, setResolving] = useState(false);
  const [resolution, setResolution] = useState("");
  const [resErr, setResErr] = useState<string>();
  const q = useQuery({ queryKey: ["ticket", id], queryFn: () => api<Ticket>(`/tickets/${id}`) });
  const alert = useQuery({ queryKey: ["alert", q.data?.alert_id], enabled: !!q.data?.alert_id, queryFn: () => api<Alert>(`/alerts/${q.data!.alert_id}`) });
  const done = (t: Ticket) => { qc.setQueryData(["ticket", id], t); qc.invalidateQueries({ queryKey: ["tickets"] }); };
  const move = useMutation({
    mutationFn: (body: { status: string; resolution?: string }) => api<Ticket>(`/tickets/${id}/status`, { method: "POST", body }),
    onSuccess: (t) => { done(t); setResolving(false); notifyOk(`Ticket ${humanize(t.status).toLowerCase()}`); },
    onError: (e) => (e instanceof ApiError && e.status === 422 ? setResErr(e.message) : notifyError(e)),
  });
  const addNote = useMutation({
    mutationFn: () => api<Ticket>(`/tickets/${id}/notes`, { method: "POST", body: { body: note } }),
    onSuccess: (t) => { done(t); setNote(""); },
    onError: (e) => notifyError(e),
  });

  if (q.isLoading) return <Spinner label="Loading ticket" />;
  if (q.error || !q.data) return <div className="card"><ErrorState error={q.error} onRetry={q.refetch} /></div>;
  const t = q.data;
  const manage = can("tickets:manage");

  return (
    <>
      <PageHeader back={{ to: "/tickets", label: "Tickets" }}
        title={<span className="flex flex-wrap items-center gap-3"><span className="mono text-ink-3 font-normal">{t.code}</span>{t.subject}</span>}
        actions={manage && <div className="flex flex-wrap gap-2">{NEXT[t.status]?.map((s) => (
          <Button key={s} variant={s === "resolved" ? "primary" : "secondary"} loading={move.isPending && move.variables?.status === s}
            onClick={() => (s === "resolved" ? (setResolving(true), setResErr(undefined)) : move.mutate({ status: s }))}>
            {t.status === "resolved" && s === "investigating" ? "Reopen" : ACTION_LABEL[s]}</Button>))}</div>} />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2 space-y-4">
          <Card className="p-5">
            <p className="text-[13px] font-medium text-ink-3 mb-1">Reported problem</p>
            <p className="whitespace-pre-wrap">{t.description}</p>
            {t.resolution && <div className="mt-4 rounded-md bg-ok-50 border border-ok-600/20 px-4 py-3"><p className="text-[13px] font-medium text-ok-700 mb-1">Resolution</p><p className="whitespace-pre-wrap text-[14px]">{t.resolution}</p></div>}
          </Card>
          <Card>
            <CardHeader title="Investigation notes" description="Internal only. Never paste client health details here." />
            <ul className="px-5 space-y-3">
              {t.notes?.length === 0 && <li className="text-[13px] text-ink-3">No notes yet.</li>}
              {t.notes?.map((n) => (
                <li key={n.id} className="border-l-2 border-brand-600/40 pl-3">
                  <p className="text-[12.5px] text-ink-3">{n.author} · {fmtDateTime(n.created_at)}</p>
                  <p className="whitespace-pre-wrap text-[14px]">{n.body}</p>
                </li>
              ))}
            </ul>
            {manage && (
              <div className="p-5 pt-4 flex flex-col gap-2">
                <Textarea aria-label="New note" rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What you checked, what you found, what you sent to the device." />
                <Button className="self-end" size="sm" disabled={!note.trim()} loading={addNote.isPending} onClick={() => addNote.mutate()}>Add note</Button>
              </div>
            )}
          </Card>
        </div>
        <div className="space-y-4">
          <Card className="p-5">
            <KV items={[
              ["Status", <StatusBadge status={t.status} />], ["Priority", <PriorityBadge value={t.priority} />], ["Reporter", t.reporter],
              ["Device", t.device_serial ? <Link className="link mono" to={`/devices/${t.device_serial}`}>{t.device_serial}</Link> : "—"],
              ["Created", fmtDateTime(t.created_at)], ["Updated", fmtDateTime(t.updated_at)],
            ]} />
          </Card>
          {alert.data && (
            <Card className="p-5">
              <p className="text-[13px] font-medium mb-2">Linked alert <span className="mono text-ink-3 font-normal">{alert.data.code}</span></p>
              <div className="flex gap-2 mb-2"><PriorityBadge value={alert.data.severity} /><StatusBadge status={alert.data.status} /></div>
              <p className="text-[13px] text-ink-2">{alert.data.message}</p>
              {alert.data.resolution && <p className="text-[12.5px] text-ink-3 mt-2">Resolved: {alert.data.resolution}</p>}
            </Card>
          )}
          <Card className="p-5 text-[13px] text-ink-2">
            Not sure where to start? <Link className="link" to="/playbooks">Open the L1 playbooks</Link>.
          </Card>
        </div>
      </div>
      {resolving && (
        <Dialog open onOpenChange={(o) => !o && setResolving(false)} title={`Resolve ${t.code}`} description="Record what fixed it so the next engineer can find it."
          footer={<><Button variant="secondary" onClick={() => setResolving(false)}>Cancel</Button>
            <Button loading={move.isPending} onClick={() => resolution.trim() ? move.mutate({ status: "resolved", resolution }) : setResErr("A resolution is required.")}>Resolve ticket</Button></>}>
          <Field label="Resolution" required error={resErr}>{(a) => <Textarea {...a} rows={4} value={resolution} onChange={(e) => { setResolution(e.target.value); setResErr(undefined); }} />}</Field>
        </Dialog>
      )}
    </>
  );
}
