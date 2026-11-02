import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import AppShell from "@/components/AppShell";
import { Restricted } from "@/components/common";
import { Spinner } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { AuthProvider, useAuth } from "@/lib/auth";
import LoginPage from "@/features/LoginPage";
import "./index.css";

const FleetPage = lazy(() => import("@/features/FleetPage"));
const AlertsPage = lazy(() => import("@/features/AlertsPage"));
const DevicesPage = lazy(() => import("@/features/DevicesPage"));
const DeviceDetail = lazy(() => import("@/features/DeviceDetail"));
const TicketsPage = lazy(() => import("@/features/TicketsPage"));
const TicketDetail = lazy(() => import("@/features/TicketDetail"));
const MessagesPage = lazy(() => import("@/features/MessagesPage"));
const FaultLab = lazy(() => import("@/features/FaultLab"));
const Playbooks = lazy(() => import("@/features/Playbooks"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 2_000, refetchOnWindowFocus: true,
    retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2 } },
});

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Spinner label="Restoring your session" />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
  return <>{children}</>;
}

function Guard({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth();
  return can(permission) ? <>{children}</> : <Restricted />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<Spinner />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route element={<RequireAuth><AppShell /></RequireAuth>}>
                <Route index element={<Guard permission="fleet:read"><FleetPage /></Guard>} />
                <Route path="alerts" element={<Guard permission="alerts:read"><AlertsPage /></Guard>} />
                <Route path="devices" element={<Guard permission="devices:read"><DevicesPage /></Guard>} />
                <Route path="devices/:serial" element={<Guard permission="devices:read"><DeviceDetail /></Guard>} />
                <Route path="tickets" element={<Guard permission="tickets:read"><TicketsPage /></Guard>} />
                <Route path="tickets/:id" element={<Guard permission="tickets:read"><TicketDetail /></Guard>} />
                <Route path="messages" element={<Guard permission="telemetry:read"><MessagesPage /></Guard>} />
                <Route path="fault-lab" element={<Guard permission="faults:manage"><FaultLab /></Guard>} />
                <Route path="playbooks" element={<Playbooks />} />
                <Route path="*" element={<div className="card p-10 text-center"><p className="font-semibold">Page not found</p></div>} />
              </Route>
            </Routes>
          </Suspense>
          <Toaster position="top-right" richColors closeButton />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
