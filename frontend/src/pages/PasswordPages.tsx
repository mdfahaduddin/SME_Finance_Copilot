import { ArrowRight, Clock, Inbox, Loader2, LockKeyhole, Mail, RotateCcw, Send, UserRound, type LucideIcon } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AuthLayout } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { FormError, PasswordField, TextField } from "../components/ui/Field";
import { StrengthMeter } from "../components/ui/StrengthMeter";
import { api, post } from "../lib/api";
import { useAuth } from "../lib/auth";

const BACK = { to: "/", label: "Back to sign in" };
const PRIMARY_LINK = "flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand-600 text-[15px] font-medium text-white shadow-md shadow-brand-600/20 hover:bg-brand-700";

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/auth/password/forgot", { email });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthLayout title="Check your email" back={BACK}
        subtitle={<>If an account exists for <b className="text-ink">{email}</b>, we've sent a link to reset your password.</>}>
        <ul className="space-y-3 rounded-xl border border-line bg-surface-2/50 p-4 text-sm text-muted">
          <Tip icon={Clock}>The link works for 60 minutes and only once.</Tip>
          <Tip icon={Inbox}>Not there after a few minutes? Check your spam or junk folder.</Tip>
        </ul>
        <Button variant="secondary" className="mt-5 h-11 w-full rounded-xl" onClick={() => setSent(false)}>
          <RotateCcw className="size-4" /> Use a different email
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Forgot your password?" back={BACK}
      subtitle="No problem. Enter the email you sign in with and we'll send you a reset link.">
      <form onSubmit={submit} className="space-y-5">
        <TextField label="Email" icon={Mail} type="email" required autoFocus autoComplete="email" value={email}
          onChange={(e) => setEmail(e.target.value)} placeholder="you@business.com" />
        <FormError message={error} />
        <Button type="submit" className="h-11 w-full rounded-xl text-[15px] shadow-md shadow-brand-600/20" disabled={busy}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} Send reset link
        </Button>
      </form>
    </AuthLayout>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (password !== confirm) return setError("Passwords do not match");
    setBusy(true);
    setError(null);
    try {
      await post("/auth/password/reset", { token, newPassword: password });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <AuthLayout title="Password updated"
        subtitle="For your security we signed you out on every device. Sign in with your new password.">
        <Link to="/" className={PRIMARY_LINK}>Continue to sign in <ArrowRight className="size-4" /></Link>
      </AuthLayout>
    );
  }

  if (!token) {
    return (
      <AuthLayout title="This link is incomplete" back={BACK}
        subtitle="The reset link is missing part of its address. Request a new one and open it straight from the email.">
        <Link to="/forgot-password" className={PRIMARY_LINK}><Send className="size-4" /> Request a new link</Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Choose a new password" back={BACK}
      subtitle="Use something you don't use anywhere else. A short sentence is easy to remember and hard to guess.">
      <form onSubmit={submit} className="space-y-4">
        <div>
          <PasswordField label="New password" icon={LockKeyhole} required minLength={10} autoFocus autoComplete="new-password"
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <StrengthMeter password={password} />
        </div>
        <PasswordField label="Confirm password" icon={LockKeyhole} required autoComplete="new-password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)}
          error={confirm && confirm !== password ? "Passwords don't match yet" : null} />
        <FormError message={error} />
        <Button type="submit" className="h-11 w-full rounded-xl text-[15px] shadow-md shadow-brand-600/20" disabled={busy}>
          {busy && <Loader2 className="size-4 animate-spin" />} Update password
        </Button>
      </form>
    </AuthLayout>
  );
}

function Tip({ icon: Icon, children }: { icon: LucideIcon; children: string }) {
  return <li className="flex gap-2.5"><Icon className="mt-0.5 size-4 shrink-0 text-brand-600 dark:text-brand-300" />{children}</li>;
}

export function AcceptInvite() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { acceptInvite } = useAuth();
  const [invite, setInvite] = useState<{ businessName: string; email: string; role: string } | null>(null);
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return setError("This invitation link is incomplete.");
    api<{ businessName: string; email: string; role: string }>(`/auth/invite/${encodeURIComponent(token)}`)
      .then(setInvite).catch((e: Error) => setError(e.message));
  }, [token]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await acceptInvite(token, name, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not accept the invitation");
      setBusy(false);
    }
  }

  return (
    <AuthLayout title={invite ? `Join ${invite.businessName}` : "Accept invitation"}
      subtitle={invite ? <>You were invited as <b className="text-ink capitalize">{invite.role}</b> ({invite.email}). Set up your sign-in to join.</> : undefined}
      back={BACK}>
      {invite ? (
        <form onSubmit={submit} className="space-y-4">
          <TextField label="Full name" icon={UserRound} required minLength={2} autoFocus autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />
          <div>
            <PasswordField label="Password" icon={LockKeyhole} required minLength={10} autoComplete="new-password"
              value={password} onChange={(e) => setPassword(e.target.value)} />
            <StrengthMeter password={password} />
          </div>
          <FormError message={error} />
          <Button type="submit" className="h-11 w-full rounded-xl text-[15px] shadow-md shadow-brand-600/20" disabled={busy}>
            {busy && <Loader2 className="size-4 animate-spin" />} Join team
          </Button>
        </form>
      ) : (
        error ? <FormError message={error} /> : <Loader2 className="mx-auto size-6 animate-spin text-muted" />
      )}
    </AuthLayout>
  );
}
