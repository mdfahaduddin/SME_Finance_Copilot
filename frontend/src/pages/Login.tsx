import { ArrowRight, Calculator, Crown, Eye, KeyRound, Loader2, LockKeyhole, Mail, type LucideIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AuthLayout, authLink } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { FormError, PasswordField, TextField } from "../components/ui/Field";
import { useAuth } from "../lib/auth";

// Demo accounts are shown only in local demo builds (VITE_DEMO_MODE=true), never in production.
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";
const DEMO: { role: string; icon: LucideIcon; email: string; password: string }[] = [
  { role: "Owner", icon: Crown, email: "owner@lotusbakery.example", password: "Owner#2026" },
  { role: "Accountant", icon: Calculator, email: "accountant@lotusbakery.example", password: "Accountant#2026" },
  { role: "Viewer", icon: Eye, email: "viewer@lotusbakery.example", password: "Viewer#2026" },
];

export default function Login() {
  const { login, verifyMfa } = useAuth();
  const [step, setStep] = useState<"password" | "mfa">("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (step === "password") {
        if (await login(email, password)) setStep("mfa");
      } else {
        await verifyMfa(code);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
    } finally {
      setBusy(false);
    }
  }

  if (step === "mfa") {
    return (
      <AuthLayout title="Two-factor verification" subtitle={<>Enter the 6-digit code from your authenticator app for <b className="text-ink">{email}</b>.</>}>
        <form onSubmit={submit} className="space-y-5">
          <label className="block text-sm font-medium text-ink">
            Authentication code
            <input inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required autoFocus
              value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} placeholder="000000"
              className="num mt-1.5 block h-14 w-full rounded-xl border border-line bg-surface text-center font-mono text-2xl tracking-[0.5em] text-ink placeholder:text-muted/40 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none" />
          </label>
          <FormError message={error} />
          <Button type="submit" className="h-11 w-full rounded-xl" disabled={busy || code.length !== 6}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />} Verify and sign in
          </Button>
          <button type="button" className="w-full text-center text-sm font-medium text-muted hover:text-ink"
            onClick={() => { setStep("password"); setCode(""); setError(null); }}>
            Use a different account
          </button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to see your cash position, alerts and financing options."
      footer={<>New to SME Finance Copilot? <Link to="/register" className={authLink}>Create an account</Link></>}
    >
      <form onSubmit={submit} className="space-y-5">
        <TextField label="Email" icon={Mail} type="email" autoComplete="username" required autoFocus value={email}
          onChange={(e) => setEmail(e.target.value)} placeholder="you@business.com" />
        <PasswordField label="Password" icon={LockKeyhole} autoComplete="current-password" required value={password}
          onChange={(e) => setPassword(e.target.value)} placeholder="Your password"
          labelAction={<Link to="/forgot-password" className="text-xs font-medium text-brand-600 hover:text-brand-700 hover:underline dark:text-brand-300">Forgot password?</Link>} />
        <FormError message={error} />
        <Button type="submit" className="group h-11 w-full rounded-xl text-[15px] shadow-md shadow-brand-600/20" disabled={busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : null} Sign in
          {!busy && <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />}
        </Button>
      </form>

      {DEMO_MODE && (
        <div className="mt-7">
          <p className="mb-3 flex items-center gap-3 text-xs font-medium text-muted">
            <span className="h-px flex-1 bg-line" />Try a demo account<span className="h-px flex-1 bg-line" />
          </p>
          <div className="grid grid-cols-3 gap-2">
            {DEMO.map(({ role, icon: Icon, email: e, password: p }) => {
              const picked = email === e;
              return (
                <button key={role} type="button" onClick={() => { setEmail(e); setPassword(p); setError(null); }} aria-pressed={picked}
                  className={`flex flex-col items-center gap-1.5 rounded-xl border px-2 py-3 text-xs font-medium transition-colors ${picked
                    ? "border-brand-400 bg-brand-50 text-brand-700 dark:border-brand-600 dark:bg-brand-900/40 dark:text-brand-200"
                    : "border-line text-ink hover:border-brand-300 hover:bg-surface-2"}`}>
                  <Icon className="size-4" /> {role}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </AuthLayout>
  );
}
