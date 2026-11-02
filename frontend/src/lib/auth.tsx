import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, setUnauthorizedHandler, tokenStore } from "./api";
import type { Me } from "./types";

type AuthState = {
  user: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  logout: (reason?: string) => void;
  can: (permission: string) => boolean;
  sessionMessage: string | null;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(Boolean(tokenStore.get()));
  const [sessionMessage, setSessionMessage] = useState<string | null>(null);

  const logout = useCallback((reason?: string) => {
    tokenStore.clear();
    setUser(null);
    qc.clear();
    setSessionMessage(reason ?? null);
  }, [qc]);

  useEffect(() => {
    setUnauthorizedHandler(() => logout("Your session expired. Sign in again to continue."));
    if (!tokenStore.get()) return;
    api<Me>("/auth/me").then(setUser).catch(() => tokenStore.clear()).finally(() => setLoading(false));
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api<{ access_token: string }>("/auth/login", { method: "POST", body: { email, password } });
    tokenStore.set(res.access_token);
    const me = await api<Me>("/auth/me");
    setSessionMessage(null);
    setUser(me);
    return me;
  }, []);

  const can = useCallback((p: string) => Boolean(user?.permissions.includes(p)), [user]);

  const value = useMemo(() => ({ user, loading, login, logout, can, sessionMessage }),
    [user, loading, login, logout, can, sessionMessage]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
