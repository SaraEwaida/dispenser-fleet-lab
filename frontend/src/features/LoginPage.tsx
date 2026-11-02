import { BellRing, FlaskConical, Wrench } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button, Field, Input } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const PASSWORD = "Demo@2026!";
const ACCOUNTS = [
  { key: "coordinator", email: "coordinator@fleet.example.com", role: "Care Coordinator", icon: BellRing,
    does: "Watch alerts around the clock; acknowledge and resolve missed doses." },
  { key: "support", email: "support@fleet.example.com", role: "Support Engineer", icon: Wrench,
    does: "Troubleshoot devices, send remote commands, work tickets." },
  { key: "qa", email: "qa@fleet.example.com", role: "QA Engineer", icon: FlaskConical,
    does: "Inject device faults and verify how the platform reacts." },
];

export default function LoginPage() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ message: string; rid?: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to={loc.state?.from ?? "/"} replace />;

  async function signIn(e: string, p: string) {
    if (!e || !p) { setError({ message: "Enter your email and password." }); return; }
    setBusy(true);
    setError(null);
    try {
      await login(e, p);
      nav(loc.state?.from ?? "/", { replace: true });
    } catch (err) {
      setError({ message: err instanceof ApiError ? err.message : "Sign-in failed.", rid: err instanceof ApiError ? err.requestId : null });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-dvh grid lg:grid-cols-[1fr_minmax(420px,500px)]">
      <section className="hidden lg:flex flex-col justify-between bg-slab text-white p-12">
        <p className="font-semibold text-lg">Dispenser Fleet</p>
        <div className="max-w-[36rem]">
          <h1 className="text-[38px] leading-[1.12] font-semibold text-white">24 dispensers. Every reminder, press and silence reaches this console.</h1>
          <p className="mt-5 text-[16px] text-white/70 max-w-[48ch]">
            Simulated medication dispensers talk to the cloud over MQTT. When a dose isn't confirmed, a device goes quiet,
            or a message arrives broken, the platform has to notice. This console is where support and QA check that it does.
          </p>
        </div>
        <p className="text-[13px] text-white/45">Simulated devices and fictional clients only. Not a medical device.</p>
      </section>
      <section className="flex flex-col justify-center px-6 py-10 sm:px-12 bg-card">
        <div className="w-full max-w-sm mx-auto">
          <h2 className="text-[24px] font-semibold">Sign in</h2>
          <p className="text-ink-3 mt-1">Choose a demo account. There is no public sign-up.</p>
          <form className="mt-6 space-y-4" noValidate onSubmit={(e: FormEvent) => { e.preventDefault(); signIn(email.trim(), password); }}>
            <Field label="Email">{(a) => <Input {...a} type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <Field label="Password">{(a) => <Input {...a} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
            {error && (
              <div role="alert" className="rounded-md bg-bad-50 px-3 py-2 text-[13px] text-bad-700">
                {error.message}{error.rid && <span className="block text-[12px] mt-0.5">Request ID <span className="font-mono">{error.rid}</span></span>}
              </div>
            )}
            <Button type="submit" size="lg" className="w-full" loading={busy}>Sign in</Button>
          </form>
          <p className="mt-8 text-[13px] font-medium">Demo accounts <span className="font-normal text-ink-3">password <span className="font-mono text-ink">{PASSWORD}</span></span></p>
          <ul className="mt-3 space-y-2">
            {ACCOUNTS.map((a) => (
              <li key={a.key}>
                <button type="button" disabled={busy} data-testid={`demo-${a.key}`} onClick={() => signIn(a.email, PASSWORD)}
                  className="w-full flex items-start gap-3 rounded-lg border border-line px-3.5 py-3 text-left hover:border-brand-600 hover:bg-brand-50/50">
                  <a.icon className="size-5 mt-0.5 text-brand-600 shrink-0" aria-hidden />
                  <span><span className="block text-[14px] font-medium">Continue as {a.role}</span>
                    <span className="block text-[12.5px] text-ink-3">{a.does}</span></span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
