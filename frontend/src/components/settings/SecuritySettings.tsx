import { KeyRound, Laptop, Loader2, LogOut, ShieldCheck, ShieldOff } from "lucide-react";
import { useState, type FormEvent } from "react";
import { post } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { errorText, toast } from "../../lib/toast";
import { useApi } from "../../lib/useApi";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { FormError, PasswordField, TextField } from "../ui/Field";

interface SessionRow { id: number; userAgent: string; createdAt: string; lastSeenAt: string; current: boolean }

function device(ua: string) {
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android"
    : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox"
    : /Safari\//.test(ua) ? "Safari" : "Browser";
  return `${browser} on ${os}`;
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/password/change", { currentPassword: current, newPassword: next });
      toast.success("Password changed", "Your other devices were signed out.");
      setCurrent("");
      setNext("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <PasswordField label="Current password" required autoComplete="current-password" value={current}
        onChange={(e) => setCurrent(e.target.value)} />
      <PasswordField label="New password" required minLength={10} autoComplete="new-password" value={next}
        onChange={(e) => setNext(e.target.value)} hint="At least 10 characters" />
      <FormError message={error} />
      <Button type="submit" size="sm" disabled={busy}>{busy ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />} Change password</Button>
    </form>
  );
}

function MfaCard() {
  const { user, refresh } = useAuth();
  const [setup, setSetup] = useState<{ secret: string; qrSvg: string } | null>(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (user?.mfaEnabled) {
    return (
      <div className="space-y-3">
        <p className="flex items-center gap-2 text-sm text-ink"><ShieldCheck className="size-4 text-success" /> Two-factor authentication is on.</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <PasswordField label="Password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <TextField label="Current code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
        </div>
        <FormError message={error} />
        <Button size="sm" variant="secondary" disabled={busy || code.length !== 6 || !password}
          onClick={() => run(async () => { await post("/auth/mfa/disable", { password, code }); setCode(""); setPassword(""); await refresh();
            toast.success("Two-factor authentication turned off"); })}>
          <ShieldOff className="size-3.5" /> Turn off
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!setup ? (
        <>
          <p className="text-sm text-muted">Protect sign-in with a code from an authenticator app (Google Authenticator, Microsoft Authenticator, 1Password...). Strongly recommended for owners.</p>
          <Button size="sm" disabled={busy} onClick={() => run(async () => setSetup(await post("/auth/mfa/setup")))}>
            <ShieldCheck className="size-3.5" /> Set up two-factor
          </Button>
        </>
      ) : (
        <div className="flex flex-col gap-4 sm:flex-row">
          <img src={setup.qrSvg} alt="QR code for your authenticator app" className="size-40 shrink-0 rounded-lg bg-white p-2" />
          <div className="min-w-0 space-y-3">
            <p className="text-sm text-ink">1. Scan the QR code with your authenticator app, or enter this key:</p>
            <code className="block rounded bg-surface-2 px-2 py-1 font-mono text-xs break-all text-ink">{setup.secret}</code>
            <TextField label="2. Enter the 6-digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            <FormError message={error} />
            <Button size="sm" disabled={busy || code.length !== 6}
              onClick={() => run(async () => { await post("/auth/mfa/enable", { code }); setSetup(null); setCode(""); await refresh();
                toast.success("Two-factor authentication is on", "You will be asked for a code when you sign in."); })}>
              Turn on
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

export function SecuritySettings() {
  const { data: sessions, reload } = useApi<SessionRow[]>("/auth/sessions");
  const [busy, setBusy] = useState(false);
  const others = sessions?.filter((s) => !s.current).length ?? 0;

  return (
    <Card className="lg:col-span-2">
      <CardHeader title="Security" subtitle="Password, two-factor authentication and signed-in devices" />
      <CardBody className="grid gap-8 lg:grid-cols-3">
        <section>
          <h4 className="mb-3 text-sm font-semibold text-ink">Password</h4>
          <PasswordForm />
        </section>
        <section>
          <h4 className="mb-3 text-sm font-semibold text-ink">Two-factor authentication</h4>
          <MfaCard />
        </section>
        <section>
          <h4 className="mb-3 text-sm font-semibold text-ink">Active sessions</h4>
          <ul className="space-y-2">
            {sessions?.map((s) => (
              <li key={s.id} className="flex items-center gap-2.5 text-sm">
                <Laptop className="size-4 shrink-0 text-muted" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-ink">{device(s.userAgent)}</span>
                  <span className="block text-xs text-muted">Active {new Date(s.lastSeenAt).toLocaleString()}</span>
                </span>
                {s.current && <Badge tone="success">this device</Badge>}
              </li>
            ))}
          </ul>
          {others > 0 && (
            <Button size="sm" variant="secondary" className="mt-3" disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await post("/auth/sessions/revoke-others");
                  await reload();
                  toast.success(`Signed out ${others} other ${others === 1 ? "session" : "sessions"}`);
                } catch (err) {
                  toast.error("Could not sign out other sessions", errorText(err));
                } finally {
                  setBusy(false);
                }
              }}>
              <LogOut className="size-3.5" /> Sign out {others} other {others === 1 ? "session" : "sessions"}
            </Button>
          )}
        </section>
      </CardBody>
    </Card>
  );
}
