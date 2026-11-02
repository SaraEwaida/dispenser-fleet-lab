/** API client: bearer auth, request-ID capture, typed error envelope. */

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api/v1";
const TOKEN_KEY = "fleet.token";

export type FieldIssue = { field: string | null; issue: string };

export class ApiError extends Error {
  status: number;
  code: string;
  details: FieldIssue[];
  requestId: string | null;
  constructor(status: number, code: string, message: string, details: FieldIssue[], requestId: string | null) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const d of this.details) if (d.field) out[d.field] = d.issue;
    return out;
  }
}

export type ApiMeta = { requestId: string | null; durationMs: number; status: number; headers: Record<string, string> };

let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn; };

export const tokenStore = {
  get: () => { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* storage unavailable */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ } },
};

type Query = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export function qs(query?: Query): string {
  if (!query) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => p.append(k, String(x)));
    else p.set(k, String(v));
  }
  const s = p.toString();
  return s ? `?${s}` : "";
}

export type RequestOptions = {
  method?: string;
  body?: unknown;
  query?: Query;
  headers?: Record<string, string>;
  rawBody?: string;
};

export async function requestWithMeta<T>(path: string, opts: RequestOptions = {}): Promise<{ data: T; meta: ApiMeta }> {
  const headers: Record<string, string> = { Accept: "application/json", ...opts.headers };
  const token = tokenStore.get();
  // An explicit empty Authorization header means "send this request unauthenticated" (API console).
  if ("Authorization" in headers) { if (!headers.Authorization) delete headers.Authorization; }
  else if (token) headers.Authorization = `Bearer ${token}`;
  let body: string | undefined;
  if (opts.rawBody !== undefined) { body = opts.rawBody; headers["Content-Type"] = "application/json"; }
  else if (opts.body !== undefined) { body = JSON.stringify(opts.body); headers["Content-Type"] = "application/json"; }

  const started = performance.now();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}${qs(opts.query)}`, { method: opts.method ?? "GET", headers, body });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "Can't reach the server. Check your connection and try again.", [], null);
  }
  const meta: ApiMeta = {
    requestId: res.headers.get("x-request-id"),
    durationMs: Math.round(performance.now() - started),
    status: res.status,
    headers: Object.fromEntries(res.headers.entries()),
  };
  const text = await res.text();
  const json = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = (json as { error?: { code?: string; message?: string; details?: FieldIssue[]; request_id?: string } })?.error;
    if (res.status === 401 && path !== "/auth/login") onUnauthorized?.();
    throw new ApiError(res.status, err?.code ?? "HTTP_ERROR", err?.message ?? `Request failed (${res.status}).`,
      err?.details ?? [], err?.request_id ?? meta.requestId);
  }
  return { data: json as T, meta };
}

export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  return (await requestWithMeta<T>(path, opts)).data;
}

function safeJson(text: string): unknown {
  try { return JSON.parse(text); } catch { return text; }
}

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };
