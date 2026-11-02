import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { Link } from "react-router-dom";
import { ErrorState, PageHeader, StatusBadge } from "@/components/common";
import { Button, Card, CardHeader, Spinner } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import { notifyError, notifyOk } from "@/lib/notify";
import type { DeviceSummary } from "@/lib/types";
import { cn, humanize } from "@/lib/utils";

type Faults = { catalog: { type: string; description: string }[]; active: { serial: string; type: string; enabled_at: string }[] };

const EXPECT: Record<string, string> = {
  offline: "Offline alert after 15 fleet minutes. On recovery, buffered messages arrive flagged Buffered and the alert auto-resolves.",
  duplicate_messages: "Second copy logged as Duplicate. Dose counts and state do not change.",
  corrupt_payload: "Message logged as Invalid with a field-level error. Nothing else changes.",
  clock_drift: "Clock drift alert. Resync command fails while the fault is on, succeeds after it is cleared.",
  no_response: "Missed dose alert 30 fleet minutes after each due time.",
  read_error: "Dispense failed alert (high) for each due dose.",
  battery_drain: "Battery low alert below 20 %, auto-resolves at 30 % or more.",
};

export default function FaultLab() {
  const qc = useQueryClient();
  const faults = useQuery({ queryKey: ["faults"], refetchInterval: 4000, queryFn: () => api<Faults>("/faults") });
  const devices = useQuery({ queryKey: ["devices", "lab"], refetchInterval: 4000, queryFn: () => api<Page<DeviceSummary>>("/devices", { query: { page_size: 100 } }) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["faults"] }); qc.invalidateQueries({ queryKey: ["devices"] }); };
  const toggle = useMutation({
    mutationFn: ({ serial, type, on }: { serial: string; type: string; on: boolean }) =>
      on ? api(`/devices/${serial}/faults/${type}`, { method: "DELETE" }) : api(`/devices/${serial}/faults`, { method: "POST", body: { type } }),
    onSuccess: (_, v) => { refresh(); notifyOk(`${humanize(v.type)} ${v.on ? "cleared" : "injected"} on ${v.serial}`); },
    onError: (e) => notifyError(e),
  });
  const clear = useMutation({
    mutationFn: () => api<{ cleared: number }>("/faults", { method: "DELETE" }),
    onSuccess: (r) => { refresh(); notifyOk(`Cleared ${r.cleared} fault${r.cleared === 1 ? "" : "s"}`); },
    onError: (e) => notifyError(e),
  });

  if (faults.isLoading || devices.isLoading) return <Spinner label="Loading Fault Lab" />;
  if (faults.error || devices.error) return <div className="card"><ErrorState error={faults.error ?? devices.error} onRetry={refresh} /></div>;
  const active = new Set(faults.data!.active.map((f) => `${f.serial}|${f.type}`));
  const catalog = faults.data!.catalog;

  return (
    <>
      <PageHeader title="Fault Lab" description="Inject faults into simulated dispensers and check that the cloud detects, alerts and recovers the way the spec says. Faults only affect the simulated device; the backend is never told to misbehave."
        actions={<Button variant="secondary" disabled={!active.size} loading={clear.isPending} onClick={() => clear.mutate()}>Clear all faults ({active.size})</Button>} />
      <div className="grid gap-4 xl:grid-cols-3 mb-4">
        {catalog.map((c) => (
          <Card key={c.type} className="p-4">
            <p className="font-medium flex items-center gap-2"><FlaskConical className="size-4 text-brand-600" />{humanize(c.type)}</p>
            <p className="text-[13px] text-ink-2 mt-1">{c.description}</p>
            <p className="text-[12.5px] text-ink-3 mt-2"><span className="font-medium text-ink-2">Expected:</span> {EXPECT[c.type]}</p>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader title="Device × fault matrix" description="Toggle a cell to inject or clear a fault. Watch the result on the Alerts page, the device page and the message log." />
        <div className="overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead><tr className="text-left text-ink-3"><th className="px-4 py-2 font-medium">Device</th><th className="px-2 py-2 font-medium">Connection</th>
              {catalog.map((c) => <th key={c.type} className="px-2 py-2 font-medium whitespace-nowrap">{humanize(c.type)}</th>)}</tr></thead>
            <tbody>
              {[...devices.data!.items].sort((a, b) => a.serial.localeCompare(b.serial)).map((d) => (
                <tr key={d.serial} className="border-t border-line">
                  <td className="px-4 py-1.5"><Link className="link mono" to={`/devices/${d.serial}`}>{d.serial}</Link></td>
                  <td className="px-2 py-1.5"><StatusBadge status={d.status} /></td>
                  {catalog.map((c) => {
                    const on = active.has(`${d.serial}|${c.type}`);
                    return (
                      <td key={c.type} className="px-2 py-1.5">
                        <button type="button" role="switch" aria-checked={on} aria-label={`${humanize(c.type)} on ${d.serial}`} data-testid={`fault-${d.serial}-${c.type}`}
                          disabled={toggle.isPending} onClick={() => toggle.mutate({ serial: d.serial, type: c.type, on })}
                          className={cn("h-6 w-11 rounded-full border transition-colors relative disabled:opacity-60", on ? "bg-brand-600 border-brand-600" : "bg-canvas border-line")}>
                          <span className={cn("absolute top-0.5 size-[18px] rounded-full bg-white shadow transition-all", on ? "left-[22px]" : "left-0.5")} />
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
