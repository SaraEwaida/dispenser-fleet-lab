import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, PageHeader, Pagination, SearchBox, StatusBadge, useDebounced } from "@/components/common";
import { Badge, Card, Select, Spinner } from "@/components/ui";
import { api, type Page } from "@/lib/api";
import type { Message } from "@/lib/types";
import { cn, hhmm, humanize } from "@/lib/utils";

export function MessageRow({ m }: { m: Message }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-line last:border-0" data-testid="message-row">
      <button className="w-full flex items-center gap-3 px-5 py-2.5 text-left hover:bg-canvas/60" aria-expanded={open} onClick={() => setOpen(!open)}>
        <ChevronRight className={cn("size-4 text-ink-3 shrink-0 transition-transform", open && "rotate-90")} />
        <span className="mono text-[12.5px] text-ink-3 w-[64px] shrink-0">{hhmm(m.received_at)}</span>
        <span className="mono text-[13px] w-[86px] shrink-0">{m.serial ?? "?"}</span>
        <span className="text-[13.5px] font-medium w-[130px] shrink-0 truncate">{m.type ? humanize(m.type) : "Unparsed"}</span>
        <StatusBadge status={m.status} />
        {m.buffered && <Badge tone="info">Buffered</Badge>}
        {m.out_of_order && <Badge tone="warn">Out of order</Badge>}
        {m.error && <span className="text-[12.5px] text-bad-700 truncate">{m.error}</span>}
        <span className="ml-auto mono text-[12px] text-ink-3 hidden md:inline">seq {m.seq ?? "—"}</span>
      </button>
      {open && (
        <div className="px-5 pb-4 pl-12 grid gap-3 text-[12.5px]">
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-ink-2">
            <span>msg_id <span className="mono">{m.msg_id ?? "—"}</span></span>
            <span>Device time <span className="mono">{m.device_ts ?? "—"}</span></span>
            <span>Received <span className="mono">{m.received_at}</span></span>
            {m.serial && <Link className="link" to={`/devices/${m.serial}`}>Open device</Link>}
          </div>
          <pre className="mono overflow-x-auto rounded-md bg-slab text-white/90 p-3 leading-relaxed">{m.payload ? JSON.stringify(m.payload, null, 2) : m.raw ?? "(empty)"}</pre>
        </div>
      )}
    </li>
  );
}

export default function MessagesPage() {
  const [params, setParams] = useSearchParams();
  const [serial, setSerial] = useState(params.get("serial") ?? "");
  const ds = useDebounced(serial.trim().toUpperCase());
  const status = params.get("status") ?? "";
  const type = params.get("type") ?? "";
  const flag = params.get("flag") ?? "";
  const [page, setPage] = useState(1);
  const set = (k: string, v: string) => { const n = new URLSearchParams(params); if (v) n.set(k, v); else n.delete(k); setParams(n, { replace: true }); setPage(1); };
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["messages", ds, status, type, flag, page], refetchInterval: page === 1 ? 3000 : false, placeholderData: (p) => p,
    queryFn: () => api<Page<Message>>("/messages", { query: { serial: ds, status, type, page, page_size: 50,
      out_of_order: flag === "ooo" ? true : undefined, buffered: flag === "buffered" ? true : undefined } }),
  });
  return (
    <>
      <PageHeader title="Message log" description="Every MQTT message the cloud received, including duplicates and rejected payloads. Click a row to see the payload." />
      <Card>
        <div className="flex flex-wrap gap-3 p-4 border-b border-line">
          <SearchBox className="w-[200px]" label="Device serial" placeholder="MD-24001" value={serial} onChange={(v) => { setSerial(v); setPage(1); }} />
          <Select aria-label="Ingestion status" className="w-auto" value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="">Any status</option>{["accepted", "duplicate", "invalid", "unknown_device"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
          <Select aria-label="Message type" className="w-auto" value={type} onChange={(e) => set("type", e.target.value)}>
            <option value="">Any type</option>{["heartbeat", "dose_due", "dose_taken", "dispense_failed", "command_ack", "boot"].map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
          </Select>
          <Select aria-label="Flags" className="w-auto" value={flag} onChange={(e) => set("flag", e.target.value)}>
            <option value="">Any flags</option><option value="buffered">Buffered (sent after reconnect)</option><option value="ooo">Out of order</option>
          </Select>
        </div>
        {error ? <ErrorState error={error} onRetry={refetch} /> : isLoading ? <Spinner label="Loading messages" /> : (
          <>
            {data?.items.length === 0 ? <EmptyState title="No messages match" /> : <ul>{data?.items.map((m) => <MessageRow key={m.id} m={m} />)}</ul>}
            {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
          </>
        )}
      </Card>
    </>
  );
}
