import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, Pagination, SearchBox, StatusBadge, Table, TableSkeleton, Td, Th, useDebounced } from "@/components/common";
import { Card, Select } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import { useSimClock } from "@/lib/sim";
import type { DeviceSummary } from "@/lib/types";
import { cn, simAgo } from "@/lib/utils";

export default function DevicesPage() {
  const nav = useNavigate();
  const { now } = useSimClock();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const dq = useDebounced(q.trim());
  const status = params.get("status") ?? "";
  const filter = params.get("filter") ?? "";
  const [page, setPage] = useState(1);
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); setPage(1); };
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["devices", dq, status, filter, page], refetchInterval: 5000, placeholderData: (p) => p,
    queryFn: () => api<Page<DeviceSummary>>("/devices", { query: { q: dq, status, page, page_size: 25,
      has_alerts: filter === "alerts" ? true : undefined, has_faults: filter === "faults" ? true : undefined } }),
  });
  return (
    <>
      <PageHeader title="Devices" description="Every dispenser, its client and live health. Devices with open alerts are listed first." />
      <Card>
        <div className="flex flex-wrap gap-3 p-4">
          <SearchBox className="flex-1 min-w-[220px]" label="Search devices" placeholder="Serial, client code, name or care team" value={q} onChange={(v) => { setQ(v); setPage(1); }} />
          <Select aria-label="Connection status" value={status} onChange={(e) => set("status", e.target.value)} className="w-auto">
            <option value="">Any connection</option><option value="online">Online</option><option value="offline">Offline</option><option value="never_seen">Never connected</option>
          </Select>
          <Select aria-label="Show" value={filter} onChange={(e) => set("filter", e.target.value)} className="w-auto">
            <option value="">All devices</option><option value="alerts">With open alerts</option><option value="faults">With injected faults</option>
          </Select>
        </div>
        {error ? <ErrorState error={error} onRetry={refetch} /> : (
          <>
            <Table>
              <thead><tr><Th>Device</Th><Th>Client</Th><Th>Connection</Th><Th>Last message</Th><Th>Battery</Th><Th>Roll</Th><Th>Clock</Th><Th>Adherence 24 h</Th><Th>Alerts</Th></tr></thead>
              {isLoading ? <TableSkeleton cols={9} /> : (
                <tbody>
                  {data?.items.length === 0 && <tr><Td colSpan={9}><EmptyState title="No devices match" body="Clear the search or filters." /></Td></tr>}
                  {data?.items.map((d) => (
                    <tr key={d.serial} className="hover:bg-canvas/60 cursor-pointer" onClick={() => nav(`/devices/${d.serial}`)}>
                      <Td><span className="mono font-medium">{d.serial}</span><span className="block text-[12px] text-ink-3">fw {d.firmware}</span></Td>
                      <Td><span className="block">{d.client.name}</span><span className="text-[12px] text-ink-3"><span className="mono">{d.client.code}</span> · {d.client.care_team}</span></Td>
                      <Td><StatusBadge status={d.status} /></Td>
                      <Td className="text-ink-2 whitespace-nowrap text-[13px]">{simAgo(d.last_seen_at, now)}</Td>
                      <Td className={cn("tabular-nums", d.battery_pct !== null && d.battery_pct < 20 && "text-bad-700 font-medium")}>{d.battery_pct ?? "—"}{d.battery_pct !== null && "%"}</Td>
                      <Td className={cn("tabular-nums", d.roll_remaining !== null && d.roll_remaining <= 2 && "text-bad-700 font-medium")}>{d.roll_remaining ?? "—"} / {d.roll_capacity}</Td>
                      <Td className={cn("tabular-nums text-[13px]", d.clock_offset_s !== null && Math.abs(d.clock_offset_s) > 300 && "text-bad-700 font-medium")}>
                        {d.clock_offset_s === null ? "—" : Math.abs(d.clock_offset_s) < 60 ? "In sync" : `${d.clock_offset_s > 0 ? "+" : ""}${Math.round(d.clock_offset_s / 60)} min`}</Td>
                      <Td className="tabular-nums">{d.adherence_24h === null ? "—" : `${d.adherence_24h}%`}<span className="block text-[12px] text-ink-3">{d.doses_24h} doses</span></Td>
                      <Td className="tabular-nums">{d.open_alerts > 0 ? <span className="font-medium text-warn-700">{d.open_alerts} open</span> : <span className="text-ink-3">None</span>}
                        {d.faults.length > 0 && <span className="block text-[12px] text-brand-700">Fault: {d.faults.join(", ")}</span>}</Td>
                    </tr>
                  ))}
                </tbody>
              )}
            </Table>
            {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
    </>
  );
}
