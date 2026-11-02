import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api";
import type { SimStatus } from "./types";

/** Simulated "now", ticking locally between server syncs (speed x real time). */
export function useSimClock() {
  const { data } = useQuery({ queryKey: ["sim"], queryFn: () => api<SimStatus>("/sim"), refetchInterval: 30_000 });
  const [syncedAt, setSyncedAt] = useState(() => Date.now());
  const [, force] = useState(0);
  useEffect(() => { if (data) setSyncedAt(Date.now()); }, [data]);
  useEffect(() => { const t = setInterval(() => force((x) => x + 1), 1000); return () => clearInterval(t); }, []);
  if (!data) return { now: undefined as string | undefined, speed: undefined as number | undefined, status: undefined };
  const now = new Date(new Date(data.now).getTime() + (Date.now() - syncedAt) * data.speed);
  return { now: now.toISOString(), speed: data.speed, status: data };
}
