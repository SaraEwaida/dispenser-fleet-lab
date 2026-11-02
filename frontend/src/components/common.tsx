import { AlertTriangle, Check, ChevronLeft, ChevronRight, Copy, Lock, Search } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "@/lib/api";
import { cn, copy, humanize } from "@/lib/utils";
import { Badge, Button, Input, type Tone } from "./ui";

// Status vocabulary → tone. Colors always ship with a text label, never alone.
const STATUS_TONE: Record<string, Tone> = {
  online: "ok", offline: "bad", never_seen: "neutral",
  open: "bad", acknowledged: "warn", resolved: "ok", investigating: "warn", escalated: "bad",
  pending: "info", taken: "ok", late: "warn", missed: "bad", failed: "bad",
  accepted: "ok", duplicate: "warn", invalid: "bad", unknown_device: "bad",
  queued: "info", sent: "info", acked: "ok", expired: "neutral",
};
const PRIORITY_TONE: Record<string, Tone> = {
  critical: "bad", urgent: "bad", high: "bad", medium: "warn", low: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "neutral"} dot>{humanize(status)}</Badge>;
}
export function PriorityBadge({ value }: { value: string }) {
  const label = /^p\d$/.test(value) ? value.toUpperCase() : humanize(value);
  return <Badge tone={PRIORITY_TONE[value] ?? "neutral"}>{label}</Badge>;
}

/** Monospace business identifier with copy-to-clipboard. */
export function IdChip({ value, to, className }: { value: string; to?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const content = to ? <Link to={to} className="mono text-sky-700 hover:underline">{value}</Link> : <span className="mono">{value}</span>;
  return (
    <span className={cn("group inline-flex items-center gap-1", className)}>
      {content}
      <button type="button" aria-label={`Copy ${value}`} title="Copy"
        onClick={() => { copy(value); setCopied(true); setTimeout(() => setCopied(false), 1200); }}
        className="opacity-0 group-hover:opacity-100 focus:opacity-100 text-ink-3 hover:text-ink transition-opacity">
        {copied ? <Check className="size-3.5 text-ok-700" /> : <Copy className="size-3.5" />}
      </button>
    </span>
  );
}

export function PageHeader({ title, description, actions, back }: {
  title: ReactNode; description?: ReactNode; actions?: ReactNode; back?: { to: string; label: string };
}) {
  return (
    <header className="mb-6">
      {back && (
        <Link to={back.to} className="inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink mb-2">
          <ChevronLeft className="size-4" /> {back.label}
        </Link>
      )}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[26px] leading-tight font-semibold">{title}</h1>
          {description && <p className="text-ink-2 mt-1 max-w-[70ch]">{description}</p>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </header>
  );
}

export function EmptyState({ title, body, action, icon }: { title: string; body?: string; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center text-center px-6 py-12">
      {icon && <div className="mb-3 text-ink-3">{icon}</div>}
      <p className="font-semibold">{title}</p>
      {body && <p className="text-ink-3 text-[13px] mt-1 max-w-[46ch]">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div role="alert" className="flex flex-col items-center text-center px-6 py-10">
      <AlertTriangle className="size-6 text-bad-700 mb-2" aria-hidden />
      <p className="font-semibold">{e?.status === 404 ? "Not found" : "This data couldn't be loaded"}</p>
      <p className="text-ink-3 text-[13px] mt-1 max-w-[52ch]">{e?.message ?? "Unexpected error."}</p>
      {e?.requestId && (
        <p className="text-[12.5px] text-ink-3 mt-2">Request ID <IdChip value={e.requestId} /> — share it with support.</p>
      )}
      {onRetry && <Button variant="secondary" size="sm" className="mt-4" onClick={onRetry}>Try again</Button>}
    </div>
  );
}

export function Restricted() {
  return (
    <div className="card">
      <EmptyState icon={<Lock className="size-6" />} title="Access restricted"
        body="Your role doesn't include this area. Switch to an account with the right role, or ask an administrator." />
    </div>
  );
}

export function SearchBox({ value, onChange, placeholder, label, className }: {
  value: string; onChange: (v: string) => void; placeholder: string; label: string; className?: string;
}) {
  return (
    <div className={cn("relative", className)}>
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-ink-3" aria-hidden />
      <Input type="search" aria-label={label} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder} className="pl-9" />
    </div>
  );
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-3 border-t border-line text-[13px] text-ink-3">
      <span>{total === 0 ? "No results" : `${from}–${to} of ${total.toLocaleString()}`}</span>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          <ChevronLeft className="size-4" />
        </Button>
        <span className="tabular-nums px-1">{page} / {pages}</span>
        <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          <ChevronRight className="size-4" />
        </Button>
      </div>
    </div>
  );
}

/** Table shell: horizontal scroll on small screens, consistent header styling. */
export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full text-left text-[13.5px] border-collapse", className)}>{children}</table>
    </div>
  );
}
export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return <th scope="col" className={cn("px-5 py-2.5 text-[12.5px] font-medium text-ink-3 bg-canvas/60 border-y border-line whitespace-nowrap", className)}>{children}</th>;
}
export function Td({ children, className, colSpan }: { children?: ReactNode; className?: string; colSpan?: number }) {
  return <td colSpan={colSpan} className={cn("px-5 py-3 border-b border-line align-middle", className)}>{children}</td>;
}

export function TableSkeleton({ rows = 6, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <tbody aria-hidden>
      {Array.from({ length: rows }).map((_, i) => (
        <tr key={i}>{Array.from({ length: cols }).map((__, j) => <Td key={j}><div className="skeleton h-3.5 w-3/4" /></Td>)}</tr>
      ))}
    </tbody>
  );
}

export function KV({ items, className }: { items: [string, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(110px,auto)_1fr] gap-x-4 gap-y-2.5 text-[13.5px]", className)}>
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-ink-3">{k}</dt>
          <dd className="min-w-0 break-words">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Horizontal segmented bar for result breakdowns (status colors + labels, never color alone). */
export function ResultBar({ passed, failed, blocked, notRun }: { passed: number; failed: number; blocked: number; notRun: number }) {
  const total = passed + failed + blocked + notRun;
  const segs = [
    { k: "Passed", v: passed, c: "bg-ok-700" }, { k: "Failed", v: failed, c: "bg-bad-700" },
    { k: "Blocked", v: blocked, c: "bg-[#c98500]" }, { k: "Not run", v: notRun, c: "bg-line-strong" },
  ];
  return (
    <div>
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full bg-canvas" role="img"
        aria-label={segs.map((s) => `${s.k} ${s.v}`).join(", ")}>
        {total > 0 && segs.filter((s) => s.v > 0).map((s) => (
          <div key={s.k} className={cn(s.c, "h-full")} style={{ width: `${(s.v / total) * 100}%` }} title={`${s.k}: ${s.v}`} />
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[12.5px] text-ink-2">
        {segs.map((s) => (
          <li key={s.k} className="flex items-center gap-1.5"><span className={cn("size-2 rounded-full", s.c)} aria-hidden />{s.k} <span className="tabular-nums font-medium text-ink">{s.v}</span></li>
        ))}
      </ul>
    </div>
  );
}
