import { useQuery } from "@tanstack/react-query";
import { BatteryLow, FlaskConical, WifiOff } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ErrorState, PageHeader, PriorityBadge } from "@/components/common";
import { Card, CardHeader, Skeleton } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import { useSimClock } from "@/lib/sim";
import type { Alert, DeviceSummary } from "@/lib/types";
import { cn, hhmm, humanize, simAgo } from "@/lib/utils";

type Summary = {
  now: string;
  devices: Record<string, number>;
  alerts: { open_by_severity: Record<string, number>; open: number; acknowledged: number; overdue: number };
  doses_24h: Record<string, number>; adherence_24h: number | null;
  messages_1h: Record<string, number>; pending_commands: number;
  dose_series: { hour: string; confirmed: number; missed: number; failed: number; pending: number }[];
};

function Stat({ label, value, sub, tone, to }: { label: string; value: string | number; sub?: string; tone?: "bad" | "warn"; to?: string }) {
  const body = (
    <div className={cn("card px-4 py-3 h-full", to && "hover:border-line-strong")}>
      <p className="text-[12.5px] text-ink-2">{label}</p>
      <p className={cn("text-[26px] font-semibold tabular-nums leading-tight mt-0.5", tone === "bad" && "text-bad-700", tone === "warn" && "text-warn-700")}>{value}</p>
      {sub && <p className="text-[12px] text-ink-3 mt-0.5">{sub}</p>}
    </div>
  );
  return to ? <Link to={to} className="block">{body}</Link> : body;
}

/** One tile per dispenser. Border and dot show the worst current condition, always with a text label. */
function DeviceTile({ d, simNow }: { d: DeviceSummary; simNow?: string }) {
  const state = d.status === "offline" ? "bad" : d.open_alerts > 0 ? "warn" : d.status === "online" ? "ok" : "idle";
  const label = d.status === "offline" ? "Offline" : d.open_alerts > 0 ? `${d.open_alerts} alert${d.open_alerts > 1 ? "s" : ""}` :
    d.status === "online" ? "OK" : "Not connected";
  return (
    <Link to={`/devices/${d.serial}`} data-testid={`tile-${d.serial}`}
      className={cn("card block p-3 border-l-4 hover:shadow-md transition-shadow",
        state === "bad" && "border-l-bad-600", state === "warn" && "border-l-warn-600", state === "ok" && "border-l-ok-600", state === "idle" && "border-l-line-strong")}>
      <div className="flex items-center justify-between gap-2">
        <span className="mono font-medium text-ink">{d.serial}</span>
        <span className={cn("inline-flex items-center gap-1 text-[12px] font-medium",
          state === "bad" && "text-bad-700", state === "warn" && "text-warn-700", state === "ok" && "text-ok-700", state === "idle" && "text-ink-3")}>
          {d.status === "offline" ? <WifiOff className="size-3.5" aria-hidden /> : <span className="size-1.5 rounded-full bg-current" aria-hidden />}
          {label}
        </span>
      </div>
      <p className="text-[12.5px] text-ink-2 truncate mt-1">{d.client.name}</p>
      <div className="mt-2 flex items-center gap-3 text-[12px] text-ink-3 tabular-nums">
        <span title="Sachets left on the roll" className={cn(d.roll_remaining !== null && d.roll_remaining <= 2 && "text-bad-700 font-medium")}>Roll {d.roll_remaining ?? "–"}/{d.roll_capacity}</span>
        <span className={cn("inline-flex items-center gap-0.5", d.battery_pct !== null && d.battery_pct < 20 && "text-bad-700 font-medium")}>
          {d.battery_pct !== null && d.battery_pct < 20 && <BatteryLow className="size-3.5" aria-hidden />}{d.battery_pct ?? "–"}%
        </span>
        <span className="ml-auto">{d.adherence_24h === null ? "" : `${Math.round(d.adherence_24h)}%`}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between text-[11.5px] text-ink-3">
        <span>{simAgo(d.last_seen_at, simNow)}</span>
        {d.faults.length > 0 && <span className="inline-flex items-center gap-1 text-brand-700" title={d.faults.join(", ")}><FlaskConical className="size-3.5" aria-hidden />{d.faults.length} fault{d.faults.length > 1 ? "s" : ""}</span>}
      </div>
    </Link>
  );
}

function DoseChart({ series }: { series: Summary["dose_series"] }) {
  const [table, setTable] = useState(false);
  const rows = series.map((r) => ({ ...r, label: hhmm(r.hour) }));
  const colors = { confirmed: "var(--color-ok-600)", missed: "var(--color-bad-600)", failed: "var(--color-warn-600)" };
  return (
    <Card>
      <CardHeader title="Dose outcomes, last 24 fleet hours" description="Confirmed (taken or late) vs. missed and failed dispenses"
        action={<button type="button" className="link text-[13px]" onClick={() => setTable((t) => !t)}>{table ? "Show chart" : "Show table"}</button>} />
      <div className="px-3 pb-4">
        {rows.length === 0 ? <p className="px-2 py-10 text-center text-ink-3 text-[13px]">No doses due yet. They appear as fleet time passes scheduled times.</p> : table ? (
          <div className="max-h-64 overflow-auto px-2"><table className="w-full text-[13px]"><thead><tr className="text-left text-ink-3"><th className="py-1 font-medium">Hour</th><th className="font-medium text-right">Confirmed</th><th className="font-medium text-right">Missed</th><th className="font-medium text-right">Failed</th></tr></thead>
            <tbody>{rows.map((r) => <tr key={r.hour} className="border-t border-line"><td className="py-1">{r.label}</td><td className="text-right tabular-nums">{r.confirmed}</td><td className="text-right tabular-nums">{r.missed}</td><td className="text-right tabular-nums">{r.failed}</td></tr>)}</tbody></table></div>
        ) : (
          <>
            <ul className="flex gap-4 px-2 pb-2 text-[12.5px] text-ink-2" aria-label="Legend">
              {(["confirmed", "missed", "failed"] as const).map((k) => <li key={k} className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: colors[k] }} />{humanize(k)}</li>)}
            </ul>
            <div className="h-56" role="img" aria-label="Bar chart of dose outcomes per hour. Use Show table for values.">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} barGap={2} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--color-line)" />
                  <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "var(--color-line-strong)" }} tick={{ fill: "var(--color-ink-3)", fontSize: 12 }} minTickGap={14} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--color-ink-3)", fontSize: 12 }} width={32} />
                  <Tooltip cursor={{ fill: "var(--color-canvas)" }} contentStyle={{ borderRadius: 8, border: "1px solid var(--color-line)", fontSize: 13 }} />
                  {(["confirmed", "missed", "failed"] as const).map((k) => <Bar key={k} dataKey={k} name={humanize(k)} fill={colors[k]} radius={[3, 3, 0, 0]} maxBarSize={16} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </>
        )}
      </div>
    </Card>
  );
}

export default function FleetPage() {
  const { now } = useSimClock();
  const summary = useQuery({ queryKey: ["summary"], refetchInterval: 3000, queryFn: () => api<Summary>("/fleet/summary") });
  const devices = useQuery({ queryKey: ["devices", "grid"], refetchInterval: 3000, queryFn: () => api<Page<DeviceSummary>>("/devices", { query: { page_size: 200 } }) });
  const alerts = useQuery({ queryKey: ["alerts", "fleet"], refetchInterval: 3000, queryFn: () => api<Page<Alert>>("/alerts", { query: { status: ["open"], page_size: 6 } }) });
  const s = summary.data;
  const grid = [...(devices.data?.items ?? [])].sort((a, b) => a.serial.localeCompare(b.serial));
  const sev = s?.alerts.open_by_severity;

  return (
    <>
      <PageHeader title="Fleet" description="Live state of every dispenser. Tiles refresh every 3 seconds." />
      {summary.error ? <div className="card"><ErrorState error={summary.error} onRetry={summary.refetch} /></div> : !s ? <Skeleton className="h-24" /> : (
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
          <Stat label="Online" value={`${s.devices.online} / ${s.devices.total}`} sub={s.devices.offline ? `${s.devices.offline} offline` : "All reachable"} tone={s.devices.offline ? "bad" : undefined} to="/devices?status=offline" />
          <Stat label="Open alerts" value={s.alerts.open} sub={sev ? `${sev.critical + sev.high} high · ${sev.medium} medium · ${sev.low} low` : ""} tone={s.alerts.open ? "warn" : undefined} to="/alerts" />
          <Stat label="Past acknowledgement SLA" value={s.alerts.overdue} sub="Open alerts nobody has picked up" tone={s.alerts.overdue ? "bad" : undefined} to="/alerts?overdue=true" />
          <Stat label="Adherence, 24 h" value={s.adherence_24h === null ? "—" : `${s.adherence_24h}%`} sub={`${s.doses_24h.taken + s.doses_24h.late} confirmed, ${s.doses_24h.missed} missed`} />
          <Stat label="Messages, last hour" value={s.messages_1h.total} sub={`${s.messages_1h.duplicate} duplicate · ${s.messages_1h.invalid} rejected`} to="/messages" />
          <Stat label="Commands in flight" value={s.pending_commands} sub="Queued or awaiting device ACK" />
        </div>
      )}

      <section className="mt-5" aria-label="Dispensers">
        <h2 className="sr-only">Dispensers</h2>
        {devices.isLoading ? <Skeleton className="h-64" /> : (
          <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 2xl:grid-cols-6">
            {grid.map((d) => <DeviceTile key={d.serial} d={d} simNow={now} />)}
          </div>
        )}
      </section>

      <div className="grid gap-4 xl:grid-cols-[1fr_420px] mt-5">
        {s && <DoseChart series={s.dose_series} />}
        <Card>
          <CardHeader title="Needs attention" action={<Link to="/alerts" className="link text-[13px]">All alerts</Link>} />
          <ul className="px-5 pb-4 divide-y divide-line">
            {alerts.data?.items.length === 0 && <li className="py-6 text-center text-[13px] text-ink-3">No open alerts.</li>}
            {alerts.data?.items.map((a) => (
              <li key={a.id} className="py-2.5">
                <div className="flex items-center gap-2"><PriorityBadge value={a.severity} />
                  <span className="text-[13.5px] font-medium">{humanize(a.type)}</span>
                  {a.overdue && <span className="text-[12px] font-medium text-bad-700">past SLA</span>}
                  <Link className="ml-auto mono link" to={`/devices/${a.device.serial}`}>{a.device.serial}</Link></div>
                <p className="text-[12.5px] text-ink-3 mt-0.5 line-clamp-2">{a.message}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
