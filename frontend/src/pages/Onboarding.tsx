import {
  ArrowLeft, ArrowRight, BellRing, Check, Clock, FileText, HandCoins, Landmark, LayoutDashboard, Lightbulb, Loader2,
  LogOut, Moon, Receipt, Rocket, ShieldCheck, Sun, Upload, type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { AccountsEditor } from "../components/data/AccountsEditor";
import { ImportPanel } from "../components/data/ImportPanel";
import { Button } from "../components/ui/Button";
import { FormError } from "../components/ui/Field";
import { post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { useTheme } from "../lib/theme";
import { toast } from "../lib/toast";
import { useApi } from "../lib/useApi";

interface Status {
  status: string;
  counts: { accounts: number; transactions: number; invoices: number; bills: number };
  monthsOfHistory: number;
  canFinish: boolean;
  recommendation: string | null;
}

type Step = 1 | 2 | 3;

const STEPS: { key: Step; title: string; text: string; icon: LucideIcon }[] = [
  { key: 1, title: "Bank accounts", text: "Today's balance for each account", icon: Landmark },
  { key: 2, title: "Import your data", text: "Statements, invoices and bills", icon: Upload },
  { key: 3, title: "You're ready", text: "Review and open your dashboard", icon: Rocket },
];

const TIPS: Record<Step, { title: string; points: string[] }> = {
  1: {
    title: "Good to know",
    points: [
      "Only the last 4 digits of an account are stored, never the full number.",
      "The forecast starts from your checking balance. Savings count as reserves.",
      "You can add or update accounts later on the Data page.",
    ],
  },
  2: {
    title: "Where to find your statement",
    points: [
      "In online banking, open the account and look for Statements or Download.",
      "PDF statements work, including scans. CSV or Excel exports work too.",
      "6 to 12 months of history gives the most reliable forecast.",
    ],
  },
  3: {
    title: "What happens next",
    points: [
      "Your dashboard shows cash position, health score and alerts.",
      "Import new statements any time. Duplicates are skipped.",
      "Invite your accountant from the Team page.",
    ],
  },
};

const HISTORY_TARGET = 12;

/** First-run setup for a new business: accounts -> data import -> finish. Full-screen, outside the app shell. */
export default function Onboarding() {
  const { user, refresh, logout } = useAuth();
  const { data: status, reload } = useApi<Status>("/onboarding/status");
  const [step, setStep] = useState<Step>(user?.business?.onboardingStatus === "data" ? 2 : 1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      await post("/onboarding/complete");
      toast.success("Setup complete", "Your dashboard is ready.");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  if (user?.role !== "owner") {
    return (
      <Frame step={null} onLogout={logout}>
        <div className="mx-auto mt-16 max-w-md rounded-2xl border border-line bg-surface p-8 text-center shadow-card">
          <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-surface-2 text-muted"><Clock className="size-7" /></span>
          <h1 className="mt-5 text-xl font-semibold text-ink">Your workspace is being set up</h1>
          <p className="mt-2 text-sm text-muted">
            The owner of {user?.business?.name} is connecting accounts and importing data. Everything will appear here once they finish.
          </p>
        </div>
      </Frame>
    );
  }

  const c = status?.counts;
  const go = (s: Step) => { setStep(s); window.scrollTo({ top: 0, behavior: "smooth" }); };

  return (
    <Frame step={step} onLogout={logout}>
      <div className="mx-auto grid max-w-6xl gap-8 lg:grid-cols-[17rem_minmax(0,1fr)] xl:gap-12">
        <StepRail step={step} onPick={(s) => s < step && go(s)} />

        <section className="min-w-0">
          <MobileProgress step={step} />

          <div className="rounded-2xl border border-line bg-surface shadow-card">
            {step === 1 && (
              <Panel
                eyebrow={`Welcome, ${user.name.split(" ")[0]}`}
                title={`Let's set up ${user.business?.name ?? "your business"}`}
                text="Add the bank accounts your business uses, with today's balance. This is where your cash forecast starts."
                footer={
                  <>
                    <span className="text-sm text-muted">{c?.accounts ? `${c.accounts} account${c.accounts === 1 ? "" : "s"} added` : "Add at least one account to continue"}</span>
                    <Button className="h-11 px-5" onClick={() => go(2)} disabled={!c?.accounts}>Continue <ArrowRight className="size-4" /></Button>
                  </>
                }
              >
                <AccountsEditor canEdit onChange={() => void reload()} />
              </Panel>
            )}

            {step === 2 && (
              <Panel
                eyebrow="Step 2 of 3"
                title="Import your history"
                text="Start with bank statements. Invoices and bills make the forecast sharper, since they tell the copilot what's coming in and going out."
                footer={
                  <>
                    <Button variant="ghost" onClick={() => go(1)}><ArrowLeft className="size-4" /> Back</Button>
                    <Button className="h-11 px-5" onClick={() => go(3)} variant={c?.transactions ? "primary" : "secondary"}>
                      {c?.transactions ? "Continue" : "Skip for now"} <ArrowRight className="size-4" />
                    </Button>
                  </>
                }
              >
                <Coverage status={status} />
                <div className="mt-6"><ImportPanel onImported={() => void reload()} /></div>
              </Panel>
            )}

            {step === 3 && status && (
              <div className="p-6 sm:p-10">
                <div className="flex flex-col items-center text-center">
                  <span className="relative grid size-16 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-lg shadow-brand-600/30">
                    <Rocket className="size-8" />
                    <span className="absolute -right-1.5 -bottom-1.5 grid size-6 place-items-center rounded-full bg-success text-white ring-4 ring-surface">
                      <Check className="size-3.5" />
                    </span>
                  </span>
                  <h2 className="mt-6 text-2xl font-semibold tracking-tight text-ink">You're ready to go</h2>
                  <p className="mt-2 max-w-md text-sm text-muted">
                    {status.counts.transactions
                      ? `Your copilot has ${status.monthsOfHistory} months of history to work with.`
                      : "No transactions yet. The dashboard fills in as soon as you import your bank history."}
                  </p>
                </div>

                <div className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Tile icon={Landmark} label="Accounts" value={status.counts.accounts} />
                  <Tile icon={FileText} label="Transactions" value={status.counts.transactions} />
                  <Tile icon={Receipt} label="Invoices" value={status.counts.invoices} />
                  <Tile icon={HandCoins} label="Bills" value={status.counts.bills} />
                </div>

                {status.recommendation && (
                  <p className="mt-5 flex items-start gap-2 rounded-xl bg-warning-soft px-4 py-3 text-sm text-ink">
                    <Lightbulb className="mt-0.5 size-4 shrink-0 text-warning" />{status.recommendation}
                  </p>
                )}

                <ul className="mt-8 grid gap-3 sm:grid-cols-3">
                  <Next icon={LayoutDashboard} title="Dashboard" text="Cash position, health score and key numbers" />
                  <Next icon={BellRing} title="Alerts" text="Early warning before cash runs short" />
                  <Next icon={ShieldCheck} title="You stay in control" text="Actions always wait for your approval" />
                </ul>

                <FormError message={error} />
                <div className="mt-8 flex flex-col-reverse items-center justify-between gap-3 border-t border-line pt-6 sm:flex-row">
                  <Button variant="ghost" onClick={() => go(2)}><ArrowLeft className="size-4" /> Import more data</Button>
                  <Button className="h-11 w-full px-6 sm:w-auto" onClick={finish} disabled={busy || !status.canFinish}>
                    {busy ? <Loader2 className="size-4 animate-spin" /> : <LayoutDashboard className="size-4" />} Go to my dashboard
                  </Button>
                </div>
              </div>
            )}
          </div>

          <Tips step={step} className="mt-6 lg:hidden" />
        </section>
      </div>
    </Frame>
  );
}

/** Page chrome: focused header (no app navigation until setup is done). */
function Frame({ step, onLogout, children }: { step: Step | null; onLogout: () => void | Promise<void>; children: ReactNode }) {
  const { theme, toggle } = useTheme();
  return (
    <div className="min-h-dvh bg-canvas">
      <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-[radial-gradient(ellipse_at_top,rgb(124_77_245/0.14),transparent_70%)]" />
      <header className="relative border-b border-line/70 bg-surface/70 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-6xl items-center gap-3 px-4 sm:px-6">
          <img src="/favicon.svg" alt="" className="size-8" />
          <span className="text-sm font-semibold text-ink">SME Finance Copilot</span>
          {step && <span className="ml-2 hidden rounded-full bg-brand-50 px-2.5 py-1 text-xs font-medium text-brand-700 sm:inline dark:bg-brand-900/40 dark:text-brand-200">Setup · Step {step} of 3</span>}
          <div className="ml-auto flex items-center gap-1">
            <button onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink">
              {theme === "dark" ? <Sun className="size-4.5" /> : <Moon className="size-4.5" />}
            </button>
            <button onClick={() => void onLogout()} className="flex h-9 items-center gap-1.5 rounded-lg px-3 text-sm text-muted hover:bg-surface-2 hover:text-ink">
              <LogOut className="size-4" /><span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>
      <main className="relative px-4 py-8 sm:px-6 sm:py-12">{children}</main>
    </div>
  );
}

function StepRail({ step, onPick }: { step: Step; onPick: (s: Step) => void }) {
  const pct = Math.round(((step - 1) / (STEPS.length - 1)) * 100);
  return (
    <aside className="hidden lg:block">
      <div className="sticky top-8 space-y-6">
        <div>
          <div className="flex items-baseline justify-between text-xs">
            <span className="font-semibold tracking-wide text-muted uppercase">Setup progress</span>
            <span className="num font-medium text-ink">{pct}%</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500" style={{ width: `${Math.max(pct, 6)}%` }} />
          </div>
        </div>

        <ol className="relative space-y-1">
          {STEPS.map(({ key, title, text, icon: Icon }, i) => {
            const state = key < step ? "done" : key === step ? "current" : "todo";
            return (
              <li key={key} className="relative">
                {i < STEPS.length - 1 && (
                  <span aria-hidden className={cn("absolute top-12 left-[1.4rem] h-[calc(100%-2.25rem)] w-px", key < step ? "bg-success" : "bg-line")} />
                )}
                <button onClick={() => onPick(key)} disabled={state === "todo"} aria-current={state === "current" ? "step" : undefined}
                  className={cn("flex w-full items-start gap-3 rounded-xl p-2 text-left transition-colors",
                    state === "current" && "bg-surface shadow-card ring-1 ring-line",
                    state === "done" && "hover:bg-surface/70")}>
                  <span className={cn("grid size-9 shrink-0 place-items-center rounded-full text-sm font-semibold",
                    state === "done" && "bg-success text-white",
                    state === "current" && "bg-brand-600 text-white shadow-md shadow-brand-600/30",
                    state === "todo" && "border border-line bg-surface text-muted")}>
                    {state === "done" ? <Check className="size-4" /> : <Icon className="size-4" />}
                  </span>
                  <span className="pt-0.5">
                    <span className={cn("block text-sm font-medium", state === "todo" ? "text-muted" : "text-ink")}>{title}</span>
                    <span className="block text-xs text-muted">{text}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>

        <Tips step={step} />
      </div>
    </aside>
  );
}

function MobileProgress({ step }: { step: Step }) {
  const current = STEPS[step - 1];
  return (
    <div className="mb-5 lg:hidden">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-ink">{current.title}</span>
        <span className="text-muted">Step {step} of 3</span>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1.5">
        {STEPS.map(({ key }) => (
          <span key={key} className={cn("h-1.5 rounded-full", key < step ? "bg-success" : key === step ? "bg-brand-600" : "bg-surface-2")} />
        ))}
      </div>
    </div>
  );
}

function Tips({ step, className }: { step: Step; className?: string }) {
  const tip = TIPS[step];
  return (
    <div className={cn("rounded-2xl border border-brand-100 bg-brand-50/60 p-4 dark:border-brand-900/60 dark:bg-brand-900/20", className)}>
      <p className="flex items-center gap-2 text-sm font-medium text-ink"><Lightbulb className="size-4 text-brand-600 dark:text-brand-300" />{tip.title}</p>
      <ul className="mt-2.5 space-y-2">
        {tip.points.map((p) => (
          <li key={p} className="flex gap-2 text-xs leading-relaxed text-muted">
            <span className="mt-1.5 size-1 shrink-0 rounded-full bg-brand-400" />{p}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Panel({ eyebrow, title, text, children, footer }: {
  eyebrow: string; title: string; text: string; children: ReactNode; footer: ReactNode;
}) {
  return (
    <>
      <div className="p-6 sm:p-8">
        <p className="text-xs font-semibold tracking-wide text-brand-600 uppercase dark:text-brand-300">{eyebrow}</p>
        <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted">{text}</p>
        <div className="mt-6">{children}</div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-b-2xl border-t border-line bg-surface-2/40 px-6 py-4 sm:px-8">
        {footer}
      </div>
    </>
  );
}

/** Live view of what has been imported, with history measured against the 12-month ideal. */
function Coverage({ status }: { status: Status | null }) {
  const c = status?.counts;
  const months = status?.monthsOfHistory ?? 0;
  const pct = Math.min(100, (months / HISTORY_TARGET) * 100);
  const tone = months >= 6 ? "bg-success" : months >= 3 ? "bg-warning" : "bg-brand-500";
  return (
    <div className="grid gap-3 sm:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,1fr))]">
      <div className="rounded-xl border border-line p-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="text-xs text-muted">History imported</span>
          <span className="num text-sm font-semibold text-ink">{months} <span className="font-normal text-muted">/ {HISTORY_TARGET} months</span></span>
        </div>
        <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-surface-2">
          <div className={cn("h-full rounded-full transition-all duration-500", tone)} style={{ width: `${pct}%` }} />
        </div>
        <p className="mt-2 text-xs text-muted">
          {months >= 6 ? "Enough for a reliable forecast." : months >= 3 ? "Health score unlocked. 6+ months sharpens the forecast." : "Import 3+ months to unlock the health score."}
        </p>
      </div>
      <MiniStat icon={FileText} label="Transactions" value={c?.transactions ?? 0} />
      <MiniStat icon={Receipt} label="Invoices" value={c?.invoices ?? 0} />
      <MiniStat icon={HandCoins} label="Bills" value={c?.bills ?? 0} />
    </div>
  );
}

function MiniStat({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line p-4 sm:flex-col sm:items-start sm:gap-2">
      <Icon className={cn("size-4", value ? "text-brand-600 dark:text-brand-300" : "text-muted")} />
      <div className="flex flex-1 items-baseline justify-between gap-2 sm:block">
        <p className="text-xs text-muted">{label}</p>
        <p className="num text-lg font-semibold text-ink">{value.toLocaleString()}</p>
      </div>
    </div>
  );
}

function Tile({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number }) {
  return (
    <div className="rounded-xl border border-line bg-surface-2/40 p-4 text-center">
      <Icon className="mx-auto size-4 text-brand-600 dark:text-brand-300" />
      <p className="num mt-2 text-xl font-semibold text-ink">{value.toLocaleString()}</p>
      <p className="text-xs text-muted">{label}</p>
    </div>
  );
}

function Next({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <li className="flex gap-3 rounded-xl border border-line p-4">
      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300">
        <Icon className="size-4" />
      </span>
      <span>
        <span className="block text-sm font-medium text-ink">{title}</span>
        <span className="block text-xs text-muted">{text}</span>
      </span>
    </li>
  );
}
