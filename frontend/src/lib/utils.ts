import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const dateFmt = new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const fullFmt = new Intl.DateTimeFormat(undefined, {
  year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit",
});

export const fmtDate = (v?: string | null) => (v ? dateFmt.format(new Date(v.length === 10 ? `${v}T00:00:00` : v)) : "—");
export const fmtDateTime = (v?: string | null) => (v ? dateTimeFmt.format(new Date(v)) : "—");
export const fmtFull = (v?: string | null) => (v ? fullFmt.format(new Date(v)) : "—");

export function timeAgo(v?: string | null): string {
  if (!v) return "—";
  const s = Math.round((Date.now() - new Date(v).getTime()) / 1000);
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d < 30 ? `${d} d ago` : fmtDate(v);
}

const ACRONYMS: Record<string, string> = { qa_engineer: "QA engineer", msg_id: "Message ID", rssi_dbm: "Signal" };
export const humanize = (s?: string | null) => s && ACRONYMS[s] ? ACRONYMS[s] : (s ? s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()) : "—");

export const fullName = (p?: { first_name: string; last_name: string } | null) => (p ? `${p.first_name} ${p.last_name}` : "—");

export const ROLE_LABEL: Record<string, string> = {
  care_coordinator: "Care Coordinator",
  support_engineer: "Support Engineer",
  qa_engineer: "QA Engineer",
};

export function todayISO(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const tz = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - tz).toISOString().slice(0, 10);
}

/** crypto.randomUUID only exists in secure contexts; fall back for plain-HTTP hosts. */
export function uid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function copy(text: string) {
  return navigator.clipboard?.writeText(text).catch(() => undefined);
}

/** Simulated-time helpers: device-domain timestamps are on the accelerated fleet clock. */
export function simAgo(v: string | null | undefined, simNow: string | undefined): string {
  if (!v || !simNow) return "—";
  const mins = Math.round((new Date(simNow).getTime() - new Date(v).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.floor(mins / 60);
  return h < 24 ? `${h} h ${mins % 60} min ago` : `${Math.floor(h / 24)} d ago`;
}

export const hhmm = (v?: string | null) =>
  v ? new Date(v).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "—";
