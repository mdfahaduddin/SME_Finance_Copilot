import { CalendarRange, Download, FileSpreadsheet, FileText, Loader2, Search, TriangleAlert, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { cn } from "../lib/cn";
import { downloadFile } from "../lib/download";
import { money, pct } from "../lib/format";
import { errorText, toast } from "../lib/toast";
import { useApi } from "../lib/useApi";

type Kind = "pnl" | "forecast" | "receivables" | "transactions";

interface Options {
  currency: string; defaultStart: string; defaultEnd: string; firstDate: string | null; lastDate: string;
  accounts: { id: number; name: string; number: string }[]; categories: string[];
}
interface PnlRow { label: string; kind: "header" | "item" | "subtotal" | "total"; values: number[] | null }
interface Pnl {
  start: string; end: string; columns: string[]; rows: PnlRow[]; partialMonths: string[];
  summary: { revenue: number; grossProfit: number; operatingProfit: number; netProfit: number; grossMargin: number; netMargin: number };
}
interface Forecast {
  asOf: string;
  summary: { openingBalance: number; lowestBalance: number; lowestWeek: number; safetyBuffer: number; endingBalance: number; shortfallAmount: number };
  weeks: { week: number; start: string; opening: number; inflows: number; outflows: number; net: number; closing: number; p10: number; p90: number; belowBuffer: boolean }[];
}
type Bucket = "current" | "1-30" | "31-60" | "61-90" | "90+";
interface Receivables {
  asOf: string; dso: number; totals: Record<Bucket | "total", number>;
  customers: ({ customer: string; invoices: number; oldestDaysPastDue: number; total: number } & Record<Bucket, number>)[];
  invoices: { invoiceNo: string; customer: string; dueDate: string; amount: number; daysPastDue: number; bucket: Bucket }[];
}
interface Transactions {
  count: number; truncated: boolean; totals: { in: number; out: number; net: number };
  rows: { date: string; account: string; description: string; counterparty: string; category: string; signed: number }[];
}

const TABS: { key: Kind; label: string; help: string }[] = [
  { key: "pnl", label: "Profit & loss", help: "Revenue, costs and profit by month" },
  { key: "forecast", label: "Cash-flow forecast", help: "The next 13 weeks, week by week" },
  { key: "receivables", label: "Aged receivables", help: "Who owes you, and for how long" },
  { key: "transactions", label: "Transactions", help: "Every ledger row, filtered" },
];
const BUCKETS: { key: Bucket; label: string; tone: string }[] = [
  { key: "current", label: "Current", tone: "bg-chart-1" },
  { key: "1-30", label: "1-30 days", tone: "bg-warning/45" },
  { key: "31-60", label: "31-60 days", tone: "bg-warning" },
  { key: "61-90", label: "61-90 days", tone: "bg-danger/70" },
  { key: "90+", label: "90+ days", tone: "bg-danger" },
];
const PRESETS = [
  ["this-month", "This month"], ["3m", "Last 3 months"], ["6m", "Last 6 months"], ["12m", "Last 12 months"],
  ["ytd", "This year"], ["last-year", "Last year"], ["custom", "Custom"],
] as const;
export type Preset = (typeof PRESETS)[number][0];

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Period for a preset, relative to the data's last date (not today: imported data can lag). */
export function presetRange(preset: Preset, lastDate: string): [string, string] {
  const end = new Date(`${lastDate}T00:00:00Z`);
  const monthsBack = (n: number) => iso(new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - (n - 1), 1)));
  switch (preset) {
    case "this-month": return [monthsBack(1), lastDate];
    case "3m": return [monthsBack(3), lastDate];
    case "6m": return [monthsBack(6), lastDate];
    case "ytd": return [`${end.getUTCFullYear()}-01-01`, lastDate];
    case "last-year": return [`${end.getUTCFullYear() - 1}-01-01`, `${end.getUTCFullYear() - 1}-12-31`];
    default: return [monthsBack(12), lastDate];
  }
}

export function query(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

const control = "h-9 rounded-lg border border-line bg-surface px-2.5 text-sm text-ink focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none";

export default function Reports() {
  const { data: opts, error: optsError } = useApi<Options>("/reports/options");
  const [kind, setKind] = useState<Kind>("pnl");
  const [preset, setPreset] = useState<Preset>("12m");
  const [range, setRange] = useState<[string, string] | null>(null);
  const [accountId, setAccountId] = useState("");
  const [category, setCategory] = useState("");
  const [direction, setDirection] = useState("");
  const [search, setSearch] = useState("");
  const [term, setTerm] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { if (opts && !range) setRange(presetRange("12m", opts.lastDate)); }, [opts, range]);
  useEffect(() => { const t = setTimeout(() => setTerm(search.trim()), 300); return () => clearTimeout(t); }, [search]);

  const usesPeriod = kind === "pnl" || kind === "transactions";
  const params = useMemo(() => {
    if (!range) return null;
    const p: Record<string, string> = {};
    if (usesPeriod) { p.start = range[0]; p.end = range[1]; }
    if (kind === "transactions") Object.assign(p, { accountId, category, direction, q: term });
    return p;
  }, [kind, range, usesPeriod, accountId, category, direction, term]);
  const path = params ? `/reports/${kind}${query(params)}` : null;

  function choosePreset(p: Preset) {
    setPreset(p);
    if (p !== "custom" && opts) setRange(presetRange(p, opts.lastDate));
  }

  async function download(format: "csv" | "xlsx" | "pdf") {
    if (!params) return;
    setBusy(format);
    const label = format === "pdf" ? "Financial summary" : TABS.find((t) => t.key === kind)!.label;
    try {
      if (format === "pdf") {
        await downloadFile("/reports/summary.pdf", "financial-summary.pdf");
      } else {
        const suffix = usesPeriod ? `-${params.start}-to-${params.end}` : "";
        await downloadFile(`/reports/${kind}${query({ ...params, format })}`, `${kind}${suffix}.${format}`);
      }
      toast.success(`${label} downloaded`, format === "pdf" ? "Two pages, ready to share with a lender." : `As ${format === "csv" ? "CSV" : "Excel"}.`);
    } catch (e) {
      toast.error("Download failed", errorText(e));
    } finally {
      setBusy(null);
    }
  }

  const filtered = kind === "transactions" && (accountId || category || direction || term);

  return (
    <>
      <PageHeader title="Reports" description="View your figures by period and download them for your bank, lender or accountant."
        actions={
          <Button onClick={() => download("pdf")} disabled={!!busy}>
            {busy === "pdf" ? <Loader2 className="size-4 animate-spin" /> : <FileText className="size-4" />} Financial summary (PDF)
          </Button>
        } />

      {/* Report tabs */}
      <div className="mb-4 grid grid-cols-2 gap-2 lg:grid-cols-4" role="tablist" aria-label="Reports">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={kind === t.key} onClick={() => setKind(t.key)}
            className={cn("rounded-xl border px-4 py-3 text-left transition-colors",
              kind === t.key ? "border-brand-400 bg-brand-50 dark:border-brand-600 dark:bg-brand-900/30" : "border-line bg-surface hover:bg-surface-2")}>
            <span className={cn("block text-sm font-semibold", kind === t.key ? "text-brand-700 dark:text-brand-200" : "text-ink")}>{t.label}</span>
            <span className="mt-0.5 block text-xs text-muted">{t.help}</span>
          </button>
        ))}
      </div>

      {/* Filters and downloads */}
      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-end gap-3 py-4">
          {usesPeriod ? (
            <>
              <label className="text-xs font-medium text-muted">Period
                <select className={cn(control, "mt-1 block")} value={preset} onChange={(e) => choosePreset(e.target.value as Preset)}>
                  {PRESETS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
              {range && (
                <div className="flex items-end gap-2">
                  <label className="text-xs font-medium text-muted">From
                    <input type="date" className={cn(control, "mt-1 block")} value={range[0]} max={range[1]}
                      onChange={(e) => { setPreset("custom"); setRange([e.target.value, range[1]]); }} />
                  </label>
                  <label className="text-xs font-medium text-muted">To
                    <input type="date" className={cn(control, "mt-1 block")} value={range[1]} min={range[0]}
                      onChange={(e) => { setPreset("custom"); setRange([range[0], e.target.value]); }} />
                  </label>
                </div>
              )}
            </>
          ) : (
            <p className="flex h-9 items-center gap-2 text-sm text-muted">
              <CalendarRange className="size-4" /> {kind === "forecast" ? "The next 13 weeks" : "Open invoices"} as of {opts?.lastDate ?? "…"}
            </p>
          )}
          {kind === "transactions" && opts && (
            <>
              <label className="text-xs font-medium text-muted">Account
                <select className={cn(control, "mt-1 block max-w-48")} value={accountId} onChange={(e) => setAccountId(e.target.value)}>
                  <option value="">All accounts</option>
                  {opts.accounts.map((a) => <option key={a.id} value={a.id}>{a.name} {a.number}</option>)}
                </select>
              </label>
              <label className="text-xs font-medium text-muted">Category
                <select className={cn(control, "mt-1 block max-w-48")} value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">All categories</option>
                  {opts.categories.map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
              <label className="text-xs font-medium text-muted">Direction
                <select className={cn(control, "mt-1 block")} value={direction} onChange={(e) => setDirection(e.target.value)}>
                  <option value="">In and out</option><option value="in">Money in</option><option value="out">Money out</option>
                </select>
              </label>
              <label className="relative text-xs font-medium text-muted">Search
                <Search className="pointer-events-none absolute bottom-2.5 left-2.5 size-4 text-muted" aria-hidden />
                <input className={cn(control, "mt-1 block w-48 pl-8")} value={search} maxLength={100} placeholder="Description or payee"
                  onChange={(e) => setSearch(e.target.value)} />
              </label>
              {filtered && (
                <button onClick={() => { setAccountId(""); setCategory(""); setDirection(""); setSearch(""); }}
                  className="flex h-9 items-center gap-1 rounded-lg px-2 text-xs font-medium text-muted hover:bg-surface-2 hover:text-ink">
                  <X className="size-3.5" /> Clear filters
                </button>
              )}
            </>
          )}
          <div className="ml-auto flex gap-2">
            <Button variant="secondary" onClick={() => download("csv")} disabled={!!busy || !params}>
              {busy === "csv" ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />} CSV
            </Button>
            <Button variant="secondary" onClick={() => download("xlsx")} disabled={!!busy || !params}>
              {busy === "xlsx" ? <Loader2 className="size-4 animate-spin" /> : <FileSpreadsheet className="size-4" />} Excel
            </Button>
          </div>
        </CardBody>
      </Card>

      {optsError ? <Card><EmptyState icon={TriangleAlert} title="Reports are unavailable" description={optsError} /></Card>
        : <ReportView key={kind} kind={kind} path={path} />}  {/* key: a new tab never renders the previous report's data */}
    </>
  );
}

function ReportView({ kind, path }: { kind: Kind; path: string | null }) {
  const { data, error, loading } = useApi<Pnl & Forecast & Receivables & Transactions>(path);
  if (error) return <Card><EmptyState icon={TriangleAlert} title="Could not load this report" description={error} /></Card>;
  if (loading || !data) return <div className="space-y-4"><Skeleton className="h-20" /><Skeleton className="h-96" /></div>;
  if (kind === "pnl") return <PnlView r={data} />;
  if (kind === "forecast") return <ForecastView r={data} />;
  if (kind === "receivables") return <ReceivablesView r={data} />;
  return <TransactionsView r={data} />;
}

function Figures({ items }: { items: { label: string; value: string; tone?: string }[] }) {
  return (
    <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
      {items.map((x) => (
        <Card key={x.label} className="px-4 py-3">
          <p className="text-xs text-muted">{x.label}</p>
          <p className={cn("num mt-1 text-lg font-semibold text-ink", x.tone)}>{x.value}</p>
        </Card>
      ))}
    </div>
  );
}

function TableCard({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">{children}</div>
      {note && <p className="border-t border-line px-5 py-3 text-xs text-muted">{note}</p>}
    </Card>
  );
}

const th = "px-4 py-2.5 text-xs font-semibold whitespace-nowrap text-muted";
const td = "px-4 py-2 whitespace-nowrap";

function PnlView({ r }: { r: Pnl }) {
  const s = r.summary;
  return (
    <>
      <Figures items={[
        { label: "Revenue", value: money(s.revenue) },
        { label: "Gross profit", value: `${money(s.grossProfit)} · ${pct(s.grossMargin)}` },
        { label: "Operating profit", value: money(s.operatingProfit) },
        { label: "Net profit", value: `${money(s.netProfit)} · ${pct(s.netMargin)}`, tone: s.netProfit < 0 ? "text-danger" : undefined },
      ]} />
      <TableCard note={<>Period {r.start} to {r.end}. {r.partialMonths.length > 0 && <>Months marked * are partial. </>}
        Interest is estimated from recorded loan balances and rates.</>}>
        <table className="w-full text-sm">
          <thead className="bg-surface-2/60">
            <tr>
              <th className={cn(th, "sticky left-0 bg-surface-2 text-left")}>Line item</th>
              {r.columns.map((c) => <th key={c} className={cn(th, "text-right")}>{c}{r.partialMonths.includes(c) && "*"}</th>)}
            </tr>
          </thead>
          <tbody>
            {r.rows.map((row, i) => (
              <tr key={i} className={cn(row.kind === "total" && "bg-brand-50/60 font-semibold dark:bg-brand-900/20",
                row.kind === "subtotal" && "font-medium", row.kind === "header" && "border-t border-line")}>
                <td className={cn(td, "sticky left-0 bg-surface", row.kind === "item" ? "pl-7 text-muted" : "text-ink",
                  row.kind === "header" && "pt-3 text-xs font-semibold tracking-wide uppercase",
                  row.kind === "total" && "bg-brand-50 dark:bg-brand-900/40")}>{row.label}</td>
                {row.values ? row.values.map((v, j) => (
                  <td key={j} className={cn(td, "num text-right", j === row.values!.length - 1 && "font-semibold",
                    v < 0 ? "text-danger" : "text-ink")}>{money(v)}</td>
                )) : <td colSpan={r.columns.length} />}
              </tr>
            ))}
          </tbody>
        </table>
      </TableCard>
    </>
  );
}

function ForecastView({ r }: { r: Forecast }) {
  const s = r.summary;
  return (
    <>
      <Figures items={[
        { label: "Today", value: money(s.openingBalance) },
        { label: `Lowest (week ${s.lowestWeek})`, value: money(s.lowestBalance), tone: s.lowestBalance < s.safetyBuffer ? "text-danger" : undefined },
        { label: "Safety buffer", value: money(s.safetyBuffer) },
        { label: "In 13 weeks", value: money(s.endingBalance) },
      ]} />
      <TableCard note={<>Weeks shaded red end below the safety buffer. P10 and P90 are the cautious and optimistic cases.</>}>
        <table className="w-full text-sm">
          <thead className="bg-surface-2/60">
            <tr>{["Week", "Starting", "Opening", "Money in", "Money out", "Net", "Closing", "Cautious (P10)", "Optimistic (P90)"].map((h, i) =>
              <th key={h} className={cn(th, i < 2 ? "text-left" : "text-right")}>{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-line">
            {r.weeks.map((w) => (
              <tr key={w.week} className={cn(w.belowBuffer && "bg-danger-soft/50")}>
                <td className={td}>{w.week}</td>
                <td className={cn(td, "text-muted")}>{w.start}</td>
                {[w.opening, w.inflows, -w.outflows, w.net, w.closing, w.p10, w.p90].map((v, i) => (
                  <td key={i} className={cn(td, "num text-right", i === 4 && "font-semibold", v < 0 ? "text-danger" : "text-ink")}>{money(v)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </TableCard>
    </>
  );
}

function ReceivablesView({ r }: { r: Receivables }) {
  const total = r.totals.total;
  if (!r.customers.length) return <Card><EmptyState icon={FileText} title="Nothing owed to you" description="There are no open invoices. Import invoices on the Data page to track who owes you." /></Card>;
  return (
    <>
      <Card className="mb-4 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm text-muted">Open invoices: <b className="num text-ink">{money(total)}</b></p>
          <p className="text-xs text-muted">Average collection {r.dso.toFixed(0)} days · as of {r.asOf}</p>
        </div>
        <div className="mt-3 flex h-3 overflow-hidden rounded-full bg-surface-2" aria-hidden>
          {BUCKETS.map((b) => r.totals[b.key] > 0 && <span key={b.key} className={b.tone} style={{ width: `${(r.totals[b.key] / total) * 100}%` }} />)}
        </div>
        <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
          {BUCKETS.map((b) => (
            <li key={b.key} className="flex items-center gap-1.5"><span className={cn("size-2.5 rounded-sm", b.tone)} />
              {b.label}: <span className="num font-medium text-ink">{money(r.totals[b.key])}</span></li>
          ))}
        </ul>
      </Card>
      <TableCard>
        <table className="w-full text-sm">
          <thead className="bg-surface-2/60">
            <tr>
              <th className={cn(th, "text-left")}>Customer</th><th className={cn(th, "text-right")}>Invoices</th>
              {BUCKETS.map((b) => <th key={b.key} className={cn(th, "text-right")}>{b.label}</th>)}
              <th className={cn(th, "text-right")}>Total</th><th className={cn(th, "text-right")}>Oldest</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {r.customers.map((c) => (
              <tr key={c.customer}>
                <td className={cn(td, "font-medium text-ink")}>{c.customer}</td>
                <td className={cn(td, "num text-right")}>{c.invoices}</td>
                {BUCKETS.map((b) => <td key={b.key} className={cn(td, "num text-right", c[b.key] ? "text-ink" : "text-muted/50")}>{c[b.key] ? money(c[b.key]) : "-"}</td>)}
                <td className={cn(td, "num text-right font-semibold")}>{money(c.total)}</td>
                <td className={cn(td, "text-right")}>{c.oldestDaysPastDue > 0
                  ? <Badge tone={c.oldestDaysPastDue > 30 ? "danger" : "warning"}>{c.oldestDaysPastDue} {c.oldestDaysPastDue === 1 ? "day" : "days"} late</Badge>
                  : <span className="text-xs text-muted">not due</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableCard>
    </>
  );
}

function TransactionsView({ r }: { r: Transactions }) {
  return (
    <>
      <Figures items={[
        { label: "Transactions", value: r.count.toLocaleString() },
        { label: "Money in", value: money(r.totals.in) },
        { label: "Money out", value: money(r.totals.out) },
        { label: "Net", value: money(r.totals.net), tone: r.totals.net < 0 ? "text-danger" : undefined },
      ]} />
      {r.count === 0 ? <Card><EmptyState icon={Search} title="No transactions match" description="Try a longer period or clear the filters." /></Card> : (
        <TableCard note={r.truncated ? <>Showing the newest {r.rows.length.toLocaleString()} of {r.count.toLocaleString()}. Download CSV or Excel for all of them.</> : undefined}>
          <table className="w-full text-sm">
            <thead className="bg-surface-2/60">
              <tr>{["Date", "Description", "Category", "Account", "Amount"].map((h, i) =>
                <th key={h} className={cn(th, i === 4 ? "text-right" : "text-left")}>{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-line">
              {r.rows.map((t, i) => (
                <tr key={i}>
                  <td className={cn(td, "text-muted")}>{t.date}</td>
                  <td className="max-w-md px-4 py-2"><span className="block truncate text-ink">{t.description || t.counterparty}</span>
                    {t.description && t.counterparty && <span className="block truncate text-xs text-muted">{t.counterparty}</span>}</td>
                  <td className={td}><Badge tone="neutral">{t.category}</Badge></td>
                  <td className={cn(td, "text-xs text-muted")}>{t.account}</td>
                  <td className={cn(td, "num text-right font-medium", t.signed < 0 ? "text-ink" : "text-success")}>{t.signed > 0 && "+"}{money(t.signed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableCard>
      )}
    </>
  );
}
