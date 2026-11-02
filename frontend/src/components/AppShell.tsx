import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useQuery } from "@tanstack/react-query";
import { BellRing, BookOpen, Cpu, FlaskConical, LayoutGrid, LifeBuoy, LogOut, Menu, Radio, Search, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, type Page } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useSimClock } from "@/lib/sim";
import { cn, ROLE_LABEL } from "@/lib/utils";

type NavItem = { to: string; label: string; icon: ReactNode; permission: string; badge?: boolean };
const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Monitor", items: [
    { to: "/", label: "Fleet", icon: <LayoutGrid />, permission: "fleet:read" },
    { to: "/alerts", label: "Alerts", icon: <BellRing />, permission: "alerts:read", badge: true },
    { to: "/devices", label: "Devices", icon: <Cpu />, permission: "devices:read" },
  ] },
  { group: "Support", items: [
    { to: "/tickets", label: "Tickets", icon: <LifeBuoy />, permission: "tickets:read" },
    { to: "/playbooks", label: "Playbooks", icon: <BookOpen />, permission: "fleet:read" },
  ] },
  { group: "Engineering", items: [
    { to: "/messages", label: "Message log", icon: <Radio />, permission: "telemetry:read" },
    { to: "/fault-lab", label: "Fault Lab", icon: <FlaskConical />, permission: "faults:manage" },
  ] },
];

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2.5 px-2" aria-label="Dispenser Fleet Console home">
      <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#2457c5" />
        <rect x="9" y="6" width="14" height="20" rx="4" fill="none" stroke="#fff" strokeWidth="2" />
        <circle cx="16" cy="12" r="3" fill="#fff" />
        <path d="M12 20h8" stroke="#fff" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <span className="leading-tight">
        <span className="block text-[15px] font-semibold text-white">Dispenser Fleet</span>
        <span className="block text-[12px] text-white/55">Support console</span>
      </span>
    </Link>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { can } = useAuth();
  const open = useQuery({
    queryKey: ["alert-count"], refetchInterval: 5000, enabled: can("alerts:read"),
    queryFn: () => api<Page<unknown>>("/alerts", { query: { status: ["open"], page_size: 1 } }),
  });
  return (
    <nav aria-label="Main" className="flex h-full flex-col bg-slab text-white/80 px-3 py-4">
      <Logo />
      <div className="mt-6 flex-1 space-y-5 overflow-y-auto">
        {NAV.map((g) => {
          const items = g.items.filter((i) => can(i.permission));
          if (!items.length) return null;
          return (
            <div key={g.group}>
              <p className="px-3 mb-1 text-[12px] text-white/45">{g.group}</p>
              <ul className="space-y-0.5">
                {items.map((i) => (
                  <li key={i.to}>
                    <NavLink to={i.to} end={i.to === "/"} onClick={onNavigate}
                      className={({ isActive }) => cn("flex items-center gap-3 rounded-md px-3 py-2 text-[14px] [&_svg]:size-[18px]",
                        isActive ? "bg-brand-600 text-white font-medium" : "hover:bg-slab-2 hover:text-white")}>
                      {i.icon}<span className="flex-1">{i.label}</span>
                      {i.badge && (open.data?.total ?? 0) > 0 && (
                        <span className="rounded-full bg-bad-600 px-1.5 text-[11.5px] font-semibold text-white tabular-nums" aria-label={`${open.data?.total} open alerts`}>{open.data?.total}</span>
                      )}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
      <p className="px-3 pt-3 text-[11.5px] leading-snug text-white/40">Simulated devices and fictional clients. Not a medical device.</p>
    </nav>
  );
}

function SimClockPill() {
  const { now, speed } = useSimClock();
  if (!now) return null;
  const d = new Date(now);
  return (
    <div className="hidden sm:flex items-center gap-2 rounded-md border border-line bg-canvas px-2.5 py-1 text-[12.5px]"
      title="The fleet runs on accelerated time so dose reminders, misses and escalations happen during a demo.">
      <span className="size-2 rounded-full bg-ok-600 animate-pulse" aria-hidden />
      <span className="text-ink-3">Fleet time</span>
      <span className="font-mono tabular-nums">{d.toLocaleDateString(undefined, { weekday: "short" })} {d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</span>
      <span className="text-ink-3">×{speed}</span>
    </div>
  );
}

function SerialJump() {
  const [v, setV] = useState("");
  const nav = useNavigate();
  const go = (e: FormEvent) => {
    e.preventDefault();
    const s = v.trim().toUpperCase();
    if (!s) return;
    nav(/^MD-\d{5}$/.test(s) ? `/devices/${s}` : `/devices?q=${encodeURIComponent(v.trim())}`);
    setV("");
  };
  return (
    <form onSubmit={go} className="relative w-full max-w-sm" role="search">
      <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-ink-3" aria-hidden />
      <input value={v} onChange={(e) => setV(e.target.value)} aria-label="Find a device by serial, client code or name"
        placeholder="Find device: MD-24007, C-1003, name…"
        className="h-9 w-full rounded-md bg-canvas border border-transparent pl-9 pr-3 text-sm placeholder:text-ink-3 focus:bg-card focus:border-brand-600 focus:outline-none" />
    </form>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  if (!user) return null;
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger className="flex items-center gap-2.5 rounded-md py-1 pl-1 pr-2 hover:bg-canvas" aria-label="Account menu">
        <span className="grid size-8 place-items-center rounded-full bg-brand-600 text-[12.5px] font-semibold text-white">
          {user.full_name.split(" ").map((s) => s[0]).join("").slice(0, 2)}
        </span>
        <span className="hidden md:block text-left leading-tight">
          <span className="block text-[13.5px] font-medium">{user.full_name}</span>
          <span className="block text-[12px] text-ink-3">{ROLE_LABEL[user.role]}</span>
        </span>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={6} className="z-50 w-56 rounded-lg border border-line bg-card p-1.5 shadow-[var(--shadow-pop)]">
          <div className="px-3 py-2"><p className="text-[13.5px] font-medium">{user.full_name}</p><p className="text-[12.5px] text-ink-3 truncate">{user.email}</p></div>
          <DropdownMenu.Separator className="my-1 h-px bg-line" />
          <DropdownMenu.Item onSelect={() => logout()} className="flex items-center gap-2 rounded-md px-3 py-2 text-[13.5px] cursor-pointer outline-none data-[highlighted]:bg-canvas">
            <LogOut className="size-4" /> Sign out
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}

export default function AppShell() {
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  useEffect(() => setDrawer(false), [loc.pathname]);
  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:z-50 focus:m-2 focus:rounded focus:bg-card focus:px-3 focus:py-2">Skip to content</a>
      <aside className="hidden lg:block fixed inset-y-0 left-0 w-[236px]"><Sidebar /></aside>
      {drawer && (
        <div className="lg:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-[260px]">
            <Sidebar onNavigate={() => setDrawer(false)} />
            <button className="absolute top-4 right-3 text-white/80" onClick={() => setDrawer(false)} aria-label="Close navigation"><X /></button>
          </div>
        </div>
      )}
      <div className="lg:pl-[236px]">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-card/95 backdrop-blur px-4 sm:px-6">
          <button className="lg:hidden rounded-md p-2 hover:bg-canvas" onClick={() => setDrawer(true)} aria-label="Open navigation"><Menu className="size-5" /></button>
          <SerialJump />
          <div className="ml-auto flex items-center gap-3"><SimClockPill /><UserMenu /></div>
        </header>
        <main id="main" className="mx-auto max-w-[1440px] px-4 py-6 sm:px-6 lg:px-8"><Outlet /></main>
      </div>
    </div>
  );
}
