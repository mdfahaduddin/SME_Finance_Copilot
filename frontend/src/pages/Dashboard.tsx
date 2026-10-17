import {
  ArrowRight, ArrowUpRight, BadgeCheck, Bot, CalendarClock, ClipboardCheck, FileUp, Landmark, Percent, Receipt,
  ShieldCheck, SlidersHorizontal, TrendingDown, TrendingUp, TriangleAlert, Wallet, type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ForecastChart, ForecastLegend } from "../components/charts/ForecastChart";
import { MonthlyChart, MonthlyLegend } from "../components/charts/MonthlyChart";
import { AlertItem } from "../components/ui/AlertItem";
import { Badge, type Tone } from "../components/ui/Badge";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { money, pct } from "../lib/format";
import type { DashboardSummary } from "../lib/types";
import { useApi } from "../lib/useApi";

function scoreTone(score: number): Tone {
  return score >= 65 ? "success" : score >= 50 ? "warning" : "danger";
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export default function Dashboard() {
  const { user } = useAuth();
  const { data, error, loading } = useApi<DashboardSummary>("/dashboard/summary");

  if (error) {
    return (
      <Card>
        <EmptyState icon={Landmark} title="Unable to load the dashboard" description={error} />
      </Card>
    );
  }
  if (loading || !data) return <DashboardSkeleton />;

  const { kpis, healthScore: hs, forecast: fc } = data;
  const cur = data.business.currency;
  const growth = kpis.revenueGrowthYoY;
  const hasHistory = data.monthly.some((m) => m.inflows || m.outflows);
  const firstName = user?.name.split(" ")[0];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-muted">{greeting()}{firstName ? `, ${firstName}` : ""}</p>
          <h1 className="mt-0.5 truncate text-2xl font-semibold tracking-tight text-ink sm:text-3xl">{data.business.name}</h1>
          <p className="mt-1 text-sm text-muted">{data.business.industry} · Data as of {formatDate(data.asOf)}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <QuickAction to="/copilot" icon={Bot} primary>Ask the copilot</QuickAction>
          <QuickAction to="/data" icon={FileUp}>Import statement</QuickAction>
          <QuickAction to="/cash-flow" icon={SlidersHorizontal}>Plan a what-if</QuickAction>
        </div>
      </div>

      {!hasHistory && (
        <div className="flex flex-wrap items-center gap-4 rounded-2xl border border-brand-200 bg-brand-50 p-5 dark:border-brand-900/60 dark:bg-brand-900/20">
          <span className="grid size-11 place-items-center rounded-xl bg-brand-600 text-white"><FileUp className="size-5" /></span>
          <div className="min-w-0 flex-1">
            <p className="font-medium text-ink">Import your bank history to bring this dashboard to life</p>
            <p className="text-sm text-muted">Forecasts, alerts and the health score are calculated from your transactions. PDF statements work.</p>
          </div>
          <Link to="/data" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-600 px-4 text-sm font-medium text-white hover:bg-brand-700">
            Import now <ArrowRight className="size-4" />
          </Link>
        </div>
      )}

      {/* Cash position + forecast */}
      <div className="grid gap-6 xl:grid-cols-3">
        <CashCard data={data} />
        <Card className="xl:col-span-2">
          <CardHeader
            title="13-week cash forecast"
            subtitle={fc.summary.firstBelowBufferWeek
              ? `Drops below the safety buffer in week ${fc.summary.firstBelowBufferWeek} (${formatDate(fc.summary.lowestWeekStart)})`
              : "Stays above the safety buffer all quarter"}
            action={
              <Link to="/cash-flow" className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700 dark:text-brand-300">
                Details & what-if <ArrowRight className="size-3.5" />
              </Link>
            }
          />
          <CardBody className="space-y-3">
            <ForecastChart weeks={fc.weeks} buffer={fc.summary.safetyBuffer} currency={cur} height={250} />
            <ForecastLegend />
          </CardBody>
        </Card>
      </div>

      {/* KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi icon={TrendingUp} label="Revenue, last 12 months" value={money(kpis.revenue12m, cur, true)}
          trend={growth === null ? undefined : { value: growth, text: `${growth >= 0 ? "+" : ""}${pct(growth)} vs last year` }}
          hint={growth === null ? "Year-on-year needs 12+ months of history" : undefined} />
        <Kpi icon={Percent} label="Net margin" value={pct(kpis.netMargin)}
          hint={kpis.netMargin >= 0.1 ? "Healthy profitability" : kpis.netMargin >= 0 ? "Thin: costs are close to revenue" : "Spending more than you earn"}
          tone={kpis.netMargin < 0 ? "danger" : kpis.netMargin < 0.05 ? "warning" : undefined} />
        <Kpi icon={Receipt} label="Overdue receivables" value={money(kpis.overdueReceivables, cur)}
          hint={kpis.dso ? `Customers pay in ${kpis.dso.toFixed(0)} days on average` : "No customer invoices yet"}
          tone={kpis.overdueReceivables > 0 ? "warning" : undefined} />
        <Kpi icon={ClipboardCheck} label="Awaiting your approval" value={String(data.pendingApprovals)}
          hint={data.pendingApprovals ? "Actions the copilot prepared for you" : "Nothing waiting"}
          to={data.pendingApprovals ? "/approvals" : undefined} />
      </div>

      {/* Alerts + health */}
      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Alerts" subtitle={data.openAlertCount ? `${data.openAlertCount} open` : "Nothing needs your attention"}
            action={data.pendingApprovals > 0
              ? <Link to="/approvals"><Badge tone="brand">{data.pendingApprovals} awaiting approval</Badge></Link> : undefined} />
          <CardBody className="divide-y divide-line pt-1">
            {data.alerts.length === 0
              ? <EmptyState icon={ShieldCheck} title="All clear" description="No open alerts. The copilot checks again every time your data changes." />
              : data.alerts.map((a) => <AlertItem key={a.id} alert={a} />)}
          </CardBody>
        </Card>
        <HealthCard hs={hs} />
      </div>

      {/* Monthly flows */}
      {hasHistory && (
        <Card>
          <CardHeader title="Money in and out by month" subtitle="All operating cash flows, last 12 months" action={<MonthlyLegend />} />
          <CardBody><MonthlyChart months={data.monthly} currency={cur} /></CardBody>
        </Card>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" });
}

function QuickAction({ to, icon: Icon, children, primary = false }: { to: string; icon: LucideIcon; children: ReactNode; primary?: boolean }) {
  return (
    <Link to={to} className={cn("inline-flex h-10 items-center gap-2 rounded-lg px-3.5 text-sm font-medium transition-colors",
      primary ? "bg-brand-600 text-white shadow-sm hover:bg-brand-700" : "border border-line bg-surface text-ink hover:bg-surface-2")}>
      <Icon className="size-4" /> {children}
    </Link>
  );
}

/** Headline card: what's in the bank now and whether it lasts the quarter. */
function CashCard({ data }: { data: DashboardSummary }) {
  const { kpis, forecast: fc } = data;
  const cur = data.business.currency;
  const s = fc.summary;
  const status = s.firstNegativeWeek
    ? { icon: TriangleAlert, text: `Runs out of cash in week ${s.firstNegativeWeek}`, cls: "bg-red-500/20 text-red-100 ring-red-300/40" }
    : s.firstBelowBufferWeek
      ? { icon: TriangleAlert, text: `Below safety buffer in week ${s.firstBelowBufferWeek}`, cls: "bg-amber-400/20 text-amber-100 ring-amber-300/40" }
      : { icon: BadgeCheck, text: "Covered for the next 13 weeks", cls: "bg-emerald-400/20 text-emerald-100 ring-emerald-300/40" };
  const StatusIcon = status.icon;

  return (
    <div className="relative overflow-hidden rounded-[var(--radius-card)] bg-gradient-to-br from-brand-600 via-brand-700 to-brand-900 p-6 text-white shadow-lg shadow-brand-900/20">
      <div aria-hidden className="absolute -top-16 -right-16 size-48 rounded-full bg-white/10 blur-2xl" />
      <div className="relative flex h-full flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="flex items-center gap-2 text-sm whitespace-nowrap text-white/80"><Wallet className="size-4" /> Operating cash</p>
          <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1", status.cls)}>
            <StatusIcon className="size-3.5" /> {status.text}
          </span>
        </div>
        <p className="num mt-3 text-4xl font-semibold tracking-tight">{money(kpis.operatingCash, cur)}</p>
        <p className="mt-1 text-sm text-white/75">
          {kpis.cashCoverMonths !== null ? `${kpis.cashCoverMonths.toFixed(1)} months of cash cover` : "Cash cover appears once outgoings are imported"}
        </p>

        <div className="mt-6 grid grid-cols-2 gap-3">
          <div className="rounded-xl bg-white/10 p-3 ring-1 ring-white/10">
            <p className="text-[11px] text-white/65">Total incl. savings</p>
            <p className="num mt-0.5 font-semibold">{money(kpis.totalCash, cur, true)}</p>
          </div>
          <div className="rounded-xl bg-white/10 p-3 ring-1 ring-white/10">
            <p className="flex items-center gap-1 text-[11px] text-white/65"><CalendarClock className="size-3" /> Lowest, 13 weeks</p>
            <p className="num mt-0.5 font-semibold">{money(s.lowestBalance, cur, true)} <span className="text-[11px] font-normal text-white/65">wk {s.lowestWeek}</span></p>
          </div>
        </div>

        {data.accounts.length > 0 && (
          <ul className="mt-5 space-y-2 border-t border-white/15 pt-4">
            {data.accounts.slice(0, 3).map((a) => (
              <li key={a.name + a.number} className="flex items-center justify-between gap-3 text-sm">
                <span className="flex min-w-0 items-center gap-2 text-white/85">
                  <Landmark className="size-3.5 shrink-0 text-white/60" />
                  <span className="truncate">{a.name}</span>
                  {a.number !== "****" && <span className="shrink-0 text-xs text-white/50">{a.number}</span>}
                </span>
                <span className="num shrink-0 font-medium">{money(a.balance, cur)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Kpi({ icon: Icon, label, value, hint, trend, tone, to }: {
  icon: LucideIcon; label: string; value: string; hint?: string;
  trend?: { value: number; text: string }; tone?: "warning" | "danger"; to?: string;
}) {
  const body = (
    <Card className={cn("h-full p-5 transition-shadow", to && "hover:shadow-md")}>
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs font-medium text-muted">{label}</p>
        <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl",
          tone === "danger" ? "bg-danger-soft text-danger" : tone === "warning" ? "bg-warning-soft text-warning"
            : "bg-brand-50 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300")}>
          <Icon className="size-4.5" aria-hidden />
        </span>
      </div>
      <p className="num mt-2 text-2xl font-semibold tracking-tight text-ink">{value}</p>
      {trend ? (
        <p className={cn("mt-1.5 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
          trend.value >= 0 ? "bg-success-soft text-success" : "bg-danger-soft text-danger")}>
          {trend.value >= 0 ? <TrendingUp className="size-3" /> : <TrendingDown className="size-3" />} {trend.text}
        </p>
      ) : hint && <p className="mt-1.5 text-xs text-muted">{hint}</p>}
      {to && <p className="mt-2 flex items-center gap-1 text-xs font-medium text-brand-600 dark:text-brand-300">Review <ArrowUpRight className="size-3" /></p>}
    </Card>
  );
  return to ? <Link to={to} className="block">{body}</Link> : body;
}

/** Score as a half-circle gauge, with the components that make it up. */
function HealthCard({ hs }: { hs: DashboardSummary["healthScore"] }) {
  const score = hs.score;
  const tone = score === null ? null : scoreTone(score);
  const stroke = tone === "success" ? "var(--color-success)" : tone === "warning" ? "var(--color-warning)" : "var(--color-danger)";
  const arc = Math.PI * 80;                                   // half-circle length for r = 80
  return (
    <Card>
      <CardHeader title="Financial health" subtitle={hs.weakestArea ? `Weakest area: ${hs.weakestArea}` : "Needs more history"}
        action={<Badge tone={tone ?? "neutral"}>{hs.grade}</Badge>} />
      <CardBody>
        {score === null ? (
          <div className="rounded-xl bg-surface-2/60 p-4 text-sm text-muted">{hs.message}</div>
        ) : (
          <div className="relative mx-auto w-52">
            <svg viewBox="0 0 200 112" className="w-full" aria-hidden>
              <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke="var(--color-surface-2)" strokeWidth="14" strokeLinecap="round" />
              <path d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke={stroke} strokeWidth="14" strokeLinecap="round"
                strokeDasharray={`${(arc * score) / 100} ${arc}`} />
            </svg>
            <div className="absolute inset-x-0 bottom-0 text-center">
              <p className="num text-4xl font-semibold tracking-tight text-ink">{score.toFixed(0)}</p>
              <p className="text-xs text-muted">out of 100</p>
            </div>
          </div>
        )}
        <ul className="mt-5 space-y-3">
          {hs.components.map((c) => (
            <li key={c.key} title={c.explanation}>
              <div className="flex justify-between gap-2 text-xs">
                <span className="font-medium text-ink">{c.label}</span>
                <span className="text-right text-muted">{c.value}</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div className={cn("h-full rounded-full", c.score >= 65 ? "bg-success" : c.score >= 40 ? "bg-warning" : "bg-danger")}
                  style={{ width: `${Math.max(c.score, 3)}%` }} />
              </div>
            </li>
          ))}
        </ul>
      </CardBody>
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-16 w-80" />
      <div className="grid gap-6 xl:grid-cols-3">
        <Skeleton className="h-80" />
        <Skeleton className="h-80 xl:col-span-2" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => <Skeleton key={i} className="h-32" />)}
      </div>
    </div>
  );
}
