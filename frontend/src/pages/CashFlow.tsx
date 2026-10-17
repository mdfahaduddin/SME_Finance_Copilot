import { CalendarClock, ChevronDown, FlaskConical, Info, Loader2, RotateCcw, ShieldAlert, TrendingDown, Wallet } from "lucide-react";
import { Fragment, useMemo, useState, type ReactNode } from "react";
import { ForecastChart, ForecastLegend } from "../components/charts/ForecastChart";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { StatTile } from "../components/ui/StatTile";
import { post } from "../lib/api";
import { cn } from "../lib/cn";
import { money } from "../lib/format";
import { useApi } from "../lib/useApi";
import { useAuth } from "../lib/auth";

/** Two significant figures: a round default such as 45,000 or 3,200,000. */
function roundNice(x: number): number {
  if (!(x > 0)) return 0;
  const p = 10 ** (Math.floor(Math.log10(x)) - 1);
  return Math.round(x / p) * p;
}

interface Week {
  week: number;
  start: string;
  end: string;
  opening: number;
  inflows: number;
  outflows: number;
  net: number;
  closing: number;
  p10: number;
  p90: number;
  inflowsByCategory: Record<string, number>;
  outflowsByCategory: Record<string, number>;
  drivers: { label: string; amount: number; direction: "in" | "out"; date: string }[];
}

interface Forecast {
  asOf: string;
  weeks: Week[];
  summary: {
    openingBalance: number; endingBalance: number; lowestBalance: number; lowestWeek: number; lowestWeekStart: string;
    lowestP10: number; safetyBuffer: number; firstNegativeWeek: number | null; firstBelowBufferWeek: number | null;
    weeksBelowBuffer: number; shortfallAmount: number; atRiskReceivables: number;
  };
  assumptions: string[];
}

interface ScenarioResult {
  changes: { type: string; description: string }[];
  baseline: Forecast["summary"];
  scenario: Forecast["summary"];
  delta: { lowestBalance: number; endingBalance: number; weeksBelowBuffer: number };
  weeks: { week: number; start: string; baseline: number; scenario: number }[];
  verdict: string;
}

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-surface px-2.5 text-sm text-ink focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs font-medium text-muted">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Toggle({ on, onChange, title, children }: { on: boolean; onChange: (v: boolean) => void; title: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-xl border p-3 transition-colors", on ? "border-brand-300 bg-brand-50/50 dark:border-brand-700 dark:bg-brand-900/20" : "border-line")}>
      <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-ink">
        <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-brand-600" />
        {title}
      </label>
      {on && <div className="mt-3 grid gap-3 sm:grid-cols-2">{children}</div>}
    </div>
  );
}

function Delta({ value }: { value: number }) {
  const tone = value > 0 ? "text-success" : value < 0 ? "text-danger" : "text-muted";
  return <span className={cn("num font-semibold", tone)}>{value > 0 ? "+" : ""}{money(value)}</span>;
}

export default function CashFlow() {
  const { user } = useAuth();
  const currency = user?.business?.currency ?? "USD";
  const { data: fc, error, loading } = useApi<Forecast>("/cashflow/forecast");
  const { data: invoices } = useApi<{ customer: string }[]>("/ledger/invoices?status=all");
  const { data: bills } = useApi<{ vendor: string }[]>("/ledger/bills?status=unpaid");
  const customers = useMemo(() => [...new Set((invoices ?? []).map((i) => i.customer))].sort(), [invoices]);
  const vendors = useMemo(() => [...new Set((bills ?? []).map((b) => b.vendor))].sort(), [bills]);

  const [openWeek, setOpenWeek] = useState<number | null>(null);
  // What-if controls
  // Amounts start empty (null) and default to about two weeks of this business's outgoings, in its own currency.
  const [expense, setExpense] = useState<{ on: boolean; amount: number | null; week: number; label: string }>(
    { on: false, amount: null, week: 6, label: "New equipment" });
  const [loan, setLoan] = useState<{ on: boolean; amount: number | null; apr: number; termMonths: number; week: number }>(
    { on: false, amount: null, apr: 9.6, termMonths: 60, week: 6 });
  const [delay, setDelay] = useState({ on: false, customer: "", days: 30 });
  const [defer, setDefer] = useState({ on: false, vendor: "", days: 14 });
  const [revenue, setRevenue] = useState({ on: false, pct: -10 });
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [running, setRunning] = useState(false);
  const [simError, setSimError] = useState<string | null>(null);

  const suggested = fc ? roundNice(fc.summary.safetyBuffer * 2) || 1000 : 1000;
  const expenseAmount = expense.amount ?? suggested;
  const loanAmount = loan.amount ?? suggested;
  const changes = [
    expense.on && { type: "one_off_expense", amount: expenseAmount, week: expense.week, label: expense.label || "One-off expense" },
    loan.on && { type: "new_loan", amount: loanAmount, apr: loan.apr / 100, termMonths: loan.termMonths, week: loan.week },
    delay.on && { type: "delay_customer", customer: delay.customer || customers[0], days: delay.days },
    defer.on && { type: "defer_bill", vendor: defer.vendor || vendors[0], days: defer.days },
    revenue.on && { type: "revenue_change", pct: revenue.pct / 100 },
  ].filter(Boolean);

  async function simulate() {
    setRunning(true);
    setSimError(null);
    try {
      setResult(await post<ScenarioResult>("/scenarios/run", { changes }));
    } catch (e) {
      setSimError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  if (error) return <Card><EmptyState icon={ShieldAlert} title="Unable to load the forecast" description={error} /></Card>;
  if (loading || !fc) {
    return <div className="space-y-4"><Skeleton className="h-28" /><Skeleton className="h-80" /></div>;
  }
  const s = fc.summary;
  const scenarioLine = result?.weeks.map((w) => ({ week: w.week, value: w.scenario }));

  return (
    <>
      <PageHeader title="Cash Flow" description={`13-week forecast from ${fc.asOf}. Recurring payments, open invoices and bills, and seasonal sales.`} />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile label="Today" value={money(s.openingBalance)} icon={Wallet} hint="Operating account" />
        <StatTile label="Lowest point" value={money(s.lowestBalance)} icon={TrendingDown}
          hint={<span className={s.lowestBalance < s.safetyBuffer ? "text-danger" : undefined}>Week {s.lowestWeek} · {s.lowestWeekStart}</span>} />
        <StatTile label="Safety buffer" value={money(s.safetyBuffer)} icon={ShieldAlert}
          hint={s.shortfallAmount > 0 ? `Gap of ${money(s.shortfallAmount)} at the low point` : "Never breached"} />
        <StatTile label="In 13 weeks" value={money(s.endingBalance)} icon={CalendarClock}
          hint={`Cautious case low: ${money(s.lowestP10)}`} />
      </div>

      <Card className="mt-6">
        <CardHeader
          title={result ? "Scenario vs baseline" : "Projected operating balance"}
          subtitle={result ? result.changes.map((c) => c.description).join(" · ") : "Hover a week for details"}
          action={result ? <Button size="sm" variant="ghost" onClick={() => setResult(null)}><RotateCcw className="size-3.5" />Clear scenario</Button> : undefined}
        />
        <CardBody className="space-y-3">
          <ForecastChart weeks={fc.weeks} buffer={s.safetyBuffer} height={300} scenario={scenarioLine} scenarioLabel="Scenario" />
          <ForecastLegend scenarioLabel={result ? "Scenario" : undefined} />
        </CardBody>
      </Card>

      <div className="mt-6 grid gap-4 xl:grid-cols-5">
        {/* What-if simulator */}
        <Card className="min-w-0 xl:col-span-2">
          <CardHeader title="What-if simulator" subtitle="Combine changes and see the effect on cash" />
          <CardBody className="space-y-3">
            <Toggle on={expense.on} onChange={(on) => setExpense({ ...expense, on })} title="One-off purchase">
              <Field label={`Amount (${currency})`}><input type="number" min={1} className={inputClass} value={expenseAmount}
                onChange={(e) => setExpense({ ...expense, amount: +e.target.value })} /></Field>
              <Field label="Week (1-13)"><input type="number" min={1} max={13} className={inputClass} value={expense.week}
                onChange={(e) => setExpense({ ...expense, week: +e.target.value })} /></Field>
              <Field label="Label"><input className={inputClass} maxLength={100} value={expense.label}
                onChange={(e) => setExpense({ ...expense, label: e.target.value })} /></Field>
            </Toggle>
            <Toggle on={loan.on} onChange={(on) => setLoan({ ...loan, on })} title="Take a loan">
              <Field label={`Amount (${currency})`}><input type="number" min={1} className={inputClass} value={loanAmount}
                onChange={(e) => setLoan({ ...loan, amount: +e.target.value })} /></Field>
              <Field label="APR (%)"><input type="number" min={0} step={0.1} className={inputClass} value={loan.apr}
                onChange={(e) => setLoan({ ...loan, apr: +e.target.value })} /></Field>
              <Field label="Term (months)"><input type="number" min={1} max={120} className={inputClass} value={loan.termMonths}
                onChange={(e) => setLoan({ ...loan, termMonths: +e.target.value })} /></Field>
              <Field label="Funded in week"><input type="number" min={1} max={13} className={inputClass} value={loan.week}
                onChange={(e) => setLoan({ ...loan, week: +e.target.value })} /></Field>
            </Toggle>
            <Toggle on={delay.on} onChange={(on) => setDelay({ ...delay, on })} title="A customer pays late">
              <Field label="Customer"><select className={inputClass} value={delay.customer || customers[0]}
                onChange={(e) => setDelay({ ...delay, customer: e.target.value })}>
                {customers.map((c) => <option key={c}>{c}</option>)}</select></Field>
              <Field label="Days later"><input type="number" min={1} max={120} className={inputClass} value={delay.days}
                onChange={(e) => setDelay({ ...delay, days: +e.target.value })} /></Field>
            </Toggle>
            <Toggle on={defer.on} onChange={(on) => setDefer({ ...defer, on })} title="Pay a supplier later">
              <Field label="Supplier"><select className={inputClass} value={defer.vendor || vendors[0]}
                onChange={(e) => setDefer({ ...defer, vendor: e.target.value })}>
                {vendors.map((v) => <option key={v}>{v}</option>)}</select></Field>
              <Field label="Days later"><input type="number" min={1} max={90} className={inputClass} value={defer.days}
                onChange={(e) => setDefer({ ...defer, days: +e.target.value })} /></Field>
            </Toggle>
            <Toggle on={revenue.on} onChange={(on) => setRevenue({ ...revenue, on })} title="Sales change">
              <Field label={`Change: ${revenue.pct > 0 ? "+" : ""}${revenue.pct}%`}>
                <input type="range" min={-50} max={50} step={5} value={revenue.pct} className="w-full accent-brand-600"
                  onChange={(e) => setRevenue({ ...revenue, pct: +e.target.value })} />
              </Field>
            </Toggle>

            <Button className="w-full" onClick={simulate} disabled={running || changes.length === 0}>
              {running ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
              Run scenario
            </Button>
            {simError && <p className="text-xs text-danger" role="alert">{simError}</p>}

            {result && (
              <div className="rounded-xl bg-surface-2 p-4">
                <p className="text-sm font-semibold text-ink">{result.verdict}</p>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
                  <div><dt className="text-muted">Lowest balance</dt><dd><Delta value={result.delta.lowestBalance} /></dd></div>
                  <div><dt className="text-muted">After 13 weeks</dt><dd><Delta value={result.delta.endingBalance} /></dd></div>
                  <div><dt className="text-muted">Weeks below buffer</dt>
                    <dd className="num font-semibold text-ink">{result.delta.weeksBelowBuffer > 0 ? "+" : ""}{result.delta.weeksBelowBuffer}</dd></div>
                </dl>
              </div>
            )}
          </CardBody>
        </Card>

        {/* Weekly table */}
        <Card className="min-w-0 xl:col-span-3">
          <CardHeader title="Week by week" subtitle="Expand a week to see what drives it" />
          <div className="overflow-x-auto px-2 pb-3">
            <table className="w-full min-w-[34rem] text-sm">
              <thead>
                <tr className="text-left text-xs text-muted">
                  <th className="px-3 py-2 font-medium">Week</th>
                  <th className="px-3 py-2 text-right font-medium">In</th>
                  <th className="px-3 py-2 text-right font-medium">Out</th>
                  <th className="px-3 py-2 text-right font-medium">Closing</th>
                  <th className="px-3 py-2 text-right font-medium">80% range</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody className="num">
                {fc.weeks.map((w) => {
                  const low = w.closing < s.safetyBuffer;
                  const open = openWeek === w.week;
                  return (
                    <Fragment key={w.week}>
                      <tr className={cn("cursor-pointer border-t border-line hover:bg-surface-2", open && "bg-surface-2")}
                        onClick={() => setOpenWeek(open ? null : w.week)}>
                        <td className="px-3 py-2 text-ink">
                          <span className="font-medium">W{w.week}</span>
                          <span className="ml-2 text-xs text-muted">{w.start}</span>
                          {low && <Badge tone="danger" className="ml-2">below buffer</Badge>}
                        </td>
                        <td className="px-3 py-2 text-right text-ink">{money(w.inflows)}</td>
                        <td className="px-3 py-2 text-right text-ink">{money(w.outflows)}</td>
                        <td className={cn("px-3 py-2 text-right font-semibold", low ? "text-danger" : "text-ink")}>{money(w.closing)}</td>
                        <td className="px-3 py-2 text-right text-xs text-muted">{money(w.p10)} to {money(w.p90)}</td>
                        <td className="px-2"><ChevronDown className={cn("size-4 text-muted transition-transform", open && "rotate-180")} /></td>
                      </tr>
                      {open && (
                        <tr className="bg-surface-2">
                          <td colSpan={6} className="px-3 pb-3">
                            <div className="grid gap-4 text-xs sm:grid-cols-3">
                              <div>
                                <p className="mb-1 font-medium text-ink">Biggest items</p>
                                {w.drivers.length === 0 && <p className="text-muted">Baseline sales only</p>}
                                {w.drivers.map((d, i) => (
                                  <p key={i} className="flex justify-between gap-2 text-muted">
                                    <span className="truncate">{d.label}</span>
                                    <span className={d.direction === "in" ? "text-success" : "text-ink"}>{d.direction === "in" ? "+" : "-"}{money(d.amount)}</span>
                                  </p>
                                ))}
                              </div>
                              <div>
                                <p className="mb-1 font-medium text-ink">Money in</p>
                                {Object.entries(w.inflowsByCategory).map(([k, v]) => (
                                  <p key={k} className="flex justify-between gap-2 text-muted"><span>{k}</span><span>{money(v)}</span></p>
                                ))}
                              </div>
                              <div>
                                <p className="mb-1 font-medium text-ink">Money out</p>
                                {Object.entries(w.outflowsByCategory).map(([k, v]) => (
                                  <p key={k} className="flex justify-between gap-2 text-muted"><span>{k}</span><span>{money(v)}</span></p>
                                ))}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <CardHeader title="How this forecast is built" />
        <CardBody>
          <ul className="space-y-1.5 text-sm text-muted">
            {fc.assumptions.map((a) => (
              <li key={a} className="flex gap-2"><Info className="mt-0.5 size-4 shrink-0 text-brand-500" />{a}</li>
            ))}
          </ul>
        </CardBody>
      </Card>
    </>
  );
}
