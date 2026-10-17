import { ArrowLeft, ArrowRight, Briefcase, Building2, Calendar, Check, Coins, Loader2, LockKeyhole, Mail, MapPin, Rocket, UserRound, Users } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AuthLayout, ILLUSTRATIONS, authLink } from "../components/layout/AuthLayout";
import { Button } from "../components/ui/Button";
import { FormError, PasswordField, SelectField, TextField } from "../components/ui/Field";
import { StrengthMeter } from "../components/ui/StrengthMeter";
import { api } from "../lib/api";
import { useAuth, type RegisterInput } from "../lib/auth";
import { cn } from "../lib/cn";

const CURRENCIES = ["USD", "EUR", "GBP", "BDT", "INR", "SGD", "AUD", "CAD", "CNY", "HKD", "AED", "MYR"];
const STEPS = ["Your business", "Your sign-in"] as const;

export default function Register() {
  const { register } = useAuth();
  const [step, setStep] = useState<0 | 1>(0);
  const [industries, setIndustries] = useState<string[]>([]);
  const [form, setForm] = useState<RegisterInput>({
    businessName: "", industry: "", region: "", foundedDate: "", employees: 1, currency: "USD",
    fullName: "", email: "", password: "", acceptTerms: false,
  });
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<string[]>("/auth/industries").then((l) => { setIndustries(l); setForm((f) => ({ ...f, industry: f.industry || l[0] })); })
      .catch(() => {});
  }, []);

  const set = <K extends keyof RegisterInput>(k: K, v: RegisterInput[K]) => setForm((f) => ({ ...f, [k]: v }));

  function next(e: FormEvent) {
    // The browser has validated step 1's required fields by the time this runs.
    e.preventDefault();
    setError(null);
    setStep(1);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (form.password !== confirm) {
      setError("Passwords do not match");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await register(form);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout illustration={ILLUSTRATIONS.register}
      title={step === 0 ? "Create your business account" : "Set up your sign-in"}
      subtitle={step === 0
        ? "Takes about 5 minutes. Next, you'll add your bank accounts and import statements."
        : <>You'll be the owner of <b className="text-ink">{form.businessName}</b>. You can invite your team later.</>}
      footer={<>Already have an account? <Link to="/" className={authLink}>Sign in</Link></>}>
      <Stepper step={step} onBack={() => setStep(0)} />

      {step === 0 ? (
        <form onSubmit={next} className="grid gap-4 sm:grid-cols-2">
          <TextField label="Business name" icon={Building2} required minLength={2} maxLength={200} autoFocus value={form.businessName}
            onChange={(e) => set("businessName", e.target.value)} placeholder="e.g. Green Leaf Grocers" className="sm:col-span-2" />
          <SelectField label="Industry" icon={Briefcase} value={form.industry} onChange={(e) => set("industry", e.target.value)} className="sm:col-span-2">
            {industries.map((i) => <option key={i}>{i}</option>)}
          </SelectField>
          <TextField label="City / region" icon={MapPin} maxLength={100} value={form.region} placeholder="Optional"
            onChange={(e) => set("region", e.target.value)} />
          <TextField label="Founded" icon={Calendar} type="date" required max={new Date().toISOString().slice(0, 10)} value={form.foundedDate}
            onChange={(e) => set("foundedDate", e.target.value)} />
          <TextField label="Employees" icon={Users} type="number" min={0} required value={form.employees}
            onChange={(e) => set("employees", Number(e.target.value))} />
          <SelectField label="Currency" icon={Coins} value={form.currency} onChange={(e) => set("currency", e.target.value)}
            hint="Used for all amounts">
            {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
          </SelectField>
          <Button type="submit" className="group h-11 rounded-xl text-[15px] shadow-md shadow-brand-600/20 sm:col-span-2">
            Continue <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
          </Button>
        </form>
      ) : (
        <form onSubmit={submit} className="space-y-4">
          <TextField label="Full name" icon={UserRound} required minLength={2} autoComplete="name" autoFocus value={form.fullName}
            onChange={(e) => set("fullName", e.target.value)} />
          <TextField label="Work email" icon={Mail} type="email" required autoComplete="email" value={form.email}
            onChange={(e) => set("email", e.target.value)} placeholder="you@business.com" />
          <div>
            <PasswordField label="Password" icon={LockKeyhole} required minLength={10} autoComplete="new-password" value={form.password}
              onChange={(e) => set("password", e.target.value)} />
            <StrengthMeter password={form.password} />
          </div>
          <PasswordField label="Confirm password" icon={LockKeyhole} required autoComplete="new-password" value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            error={confirm && confirm !== form.password ? "Passwords don't match yet" : null} />

          <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line bg-surface-2/50 p-3.5 text-sm text-ink has-[:checked]:border-brand-300 has-[:checked]:bg-brand-50/60 dark:has-[:checked]:border-brand-700 dark:has-[:checked]:bg-brand-900/20">
            <input type="checkbox" required checked={form.acceptTerms} onChange={(e) => set("acceptTerms", e.target.checked)}
              className="mt-0.5 size-4 shrink-0 accent-brand-600" />
            <span className="leading-snug">I agree to the Terms of Service and Privacy Policy, and confirm I'm authorised to act for this business.</span>
          </label>
          <FormError message={error} />
          <div className="flex gap-3">
            <Button type="button" variant="secondary" className="h-11 rounded-xl px-4" onClick={() => setStep(0)}>
              <ArrowLeft className="size-4" /> Back
            </Button>
            <Button type="submit" className="h-11 flex-1 rounded-xl text-[15px] shadow-md shadow-brand-600/20" disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Rocket className="size-4" />} Create account
            </Button>
          </div>
        </form>
      )}
    </AuthLayout>
  );
}

function Stepper({ step, onBack }: { step: 0 | 1; onBack: () => void }) {
  return (
    <ol className="mb-6 flex items-center gap-3" aria-label="Registration steps">
      {STEPS.map((label, i) => {
        const done = i < step;
        const current = i === step;
        const content = (
          <>
            <span className={cn("grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold transition-colors",
              done ? "bg-success text-white" : current ? "bg-brand-600 text-white" : "bg-surface-2 text-muted")}>
              {done ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
            </span>
            <span className={cn("truncate text-sm font-medium", current ? "text-ink" : "text-muted")}>{label}</span>
          </>
        );
        return (
          <li key={label} className="flex min-w-0 flex-1 items-center gap-3" aria-current={current ? "step" : undefined}>
            {done ? (
              <button type="button" onClick={onBack} className="flex min-w-0 items-center gap-2 rounded-md hover:opacity-80">{content}</button>
            ) : <span className="flex min-w-0 items-center gap-2">{content}</span>}
            {i < STEPS.length - 1 && <span className={cn("h-px flex-1", done ? "bg-success" : "bg-line")} />}
          </li>
        );
      })}
    </ol>
  );
}
