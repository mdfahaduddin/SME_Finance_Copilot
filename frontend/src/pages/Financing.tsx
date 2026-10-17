import { ArrowRightLeft, CheckCircle2, ChevronDown, Clock, HandCoins, Loader2, Search, Sparkles, TriangleAlert, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApprovalCard } from "../components/chat/ApprovalCard";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { notifyApprovalsChanged } from "../lib/events";
import { money, pct } from "../lib/format";
import { toast } from "../lib/toast";
import type { ApprovalRequest } from "../lib/types";

interface Eligible {
  productId: number; rank: number; lender: string; name: string; type: string; description: string; score: number;
  scores: Record<"cost" | "fit" | "approval" | "affordability" | "speed", number>;
  estimatedApr: number; effectiveApr: number; termMonths: number; monthlyPayment: number; totalCost: number;
  fundingDays: number; dscrAfter: number; reasons: string[]; watchOuts: string[];
}
interface Ineligible { productId: number; lender: string; name: string; type: string; ineligibleReasons: string[]; partialAmount?: number }
interface MatchResult {
  currency?: string;
  /** Lender limits converted into the business currency (empty when no conversion was needed). */
  fx?: { from: string; to: string; rate: number }[];
  need: { amount: number; purpose: string; termMonths: number | null; neededWithinDays: number | null; source: string } | null;
  eligible: Eligible[];
  ineligible: Ineligible[];
  weights?: Record<string, number>;
  disclaimer?: string;
  message?: string;
}

const PURPOSES = [
  ["working_capital", "Working capital"], ["bridge", "Bridge a cash gap"], ["equipment", "Equipment"],
  ["expansion", "Expansion"], ["refinance", "Refinance"],
] as const;

const SCORE_LABELS: Record<keyof Eligible["scores"], string> = {
  cost: "Cost", fit: "Fit", approval: "Approval odds", affordability: "Affordability", speed: "Speed",
};

const TYPE_LABEL: Record<string, string> = {
  term_loan: "Term loan", credit_line: "Credit line", invoice_finance: "Invoice finance", equipment: "Equipment",
  merchant_advance: "Cash advance", gov_grant: "Grant",
};

const inputClass =
  "h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none";

function ScoreBars({ scores, weights }: { scores: Eligible["scores"]; weights?: Record<string, number> }) {
  return (
    <div className="grid grid-cols-5 gap-2">
      {(Object.keys(SCORE_LABELS) as (keyof Eligible["scores"])[]).map((k) => (
        <div key={k} title={`${SCORE_LABELS[k]}: ${scores[k].toFixed(0)}/100${weights ? ` (weight ${pct(weights[k], 0)})` : ""}`}>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-chart-1" style={{ width: `${scores[k]}%` }} />
          </div>
          <p className="mt-1 truncate text-[10px] text-muted">{SCORE_LABELS[k]}</p>
        </div>
      ))}
    </div>
  );
}

function OfferCard({ e, weights, canApply, purpose, amount }: {
  e: Eligible; weights?: Record<string, number>; canApply: boolean; purpose: string; amount: number;
}) {
  const [request, setRequest] = useState<ApprovalRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function apply() {
    setBusy(true);
    setError(null);
    try {
      setRequest(await post<ApprovalRequest>("/approvals", {
        tool: "submit_loan_application",
        params: { productId: e.productId, amount, termMonths: e.termMonths, purpose: purpose.replace("_", " ") },
        rationale: `Ranked #${e.rank} (score ${e.score.toFixed(0)}) for this need.`,
      }));
      notifyApprovalsChanged();
      toast.success("Application sent for approval", `${e.lender} · ${e.name}. Nothing is submitted until an owner approves it.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const top = e.rank === 1;
  return (
    <Card className={cn("p-5", top && "ring-2 ring-brand-500/40")}>
      <div className="flex flex-wrap items-start gap-3">
        <span className={cn("grid size-9 shrink-0 place-items-center rounded-xl text-sm font-semibold",
          top ? "bg-brand-600 text-white" : "bg-surface-2 text-muted")}>#{e.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-ink">{e.lender} · {e.name}</h3>
            <Badge tone="neutral">{TYPE_LABEL[e.type] ?? e.type}</Badge>
            {top && <Badge tone="brand"><Sparkles className="size-3" />Best match</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-muted">{e.description}</p>
        </div>
        <div className="text-right">
          <p className="num text-2xl font-semibold text-ink">{e.score.toFixed(0)}</p>
          <p className="text-[11px] text-muted">match score</p>
        </div>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div><dt className="text-muted">Est. APR</dt><dd className="num mt-0.5 text-sm font-semibold text-ink">{e.type === "gov_grant" ? "None" : pct(e.estimatedApr)}</dd></div>
        <div><dt className="text-muted">Monthly</dt><dd className="num mt-0.5 text-sm font-semibold text-ink">{money(e.monthlyPayment)}</dd></div>
        <div><dt className="text-muted">Total cost</dt><dd className="num mt-0.5 text-sm font-semibold text-ink">{money(e.totalCost)}</dd></div>
        <div><dt className="text-muted">Funds in</dt><dd className="num mt-0.5 text-sm font-semibold text-ink">{e.fundingDays} day{e.fundingDays !== 1 && "s"}</dd></div>
      </dl>

      <div className="mt-4"><ScoreBars scores={e.scores} weights={weights} /></div>

      <div className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
        <ul className="space-y-1">
          {e.reasons.map((r) => <li key={r} className="flex gap-1.5 text-ink"><CheckCircle2 className="mt-px size-3.5 shrink-0 text-success" />{r}</li>)}
        </ul>
        <ul className="space-y-1">
          {e.watchOuts.map((w) => <li key={w} className="flex gap-1.5 text-ink"><TriangleAlert className="mt-px size-3.5 shrink-0 text-warning" />{w}</li>)}
          <li className="flex gap-1.5 text-muted"><Clock className="mt-px size-3.5 shrink-0" />{e.termMonths ? `${e.termMonths}-month term` : "No repayment"} · DSCR after: {e.dscrAfter.toFixed(2)}x</li>
        </ul>
      </div>

      {canApply && !request && (
        <div className="mt-4 flex items-center gap-3 border-t border-line pt-4">
          <Button size="sm" variant={top ? "primary" : "secondary"} onClick={apply} disabled={busy}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <HandCoins className="size-3.5" />}
            Request application
          </Button>
          <p className="text-[11px] text-muted">Creates an approval request. Nothing is submitted until the owner approves.</p>
        </div>
      )}
      {error && <p className="mt-3 text-xs text-danger" role="alert">{error}</p>}
      {request && <div className="mt-4"><ApprovalCard requestId={request.id} /></div>}
    </Card>
  );
}

export default function Financing() {
  const { user } = useAuth();
  const currency = user?.business?.currency ?? "USD";
  const [amount, setAmount] = useState("");
  const [purpose, setPurpose] = useState<string>("equipment");
  const [term, setTerm] = useState<string>("");
  const [within, setWithin] = useState<string>("");
  const [result, setResult] = useState<MatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showIneligible, setShowIneligible] = useState(false);

  async function run(body: object) {
    setBusy(true);
    setError(null);
    try {
      setResult(await post<MatchResult>("/financing/match", body));
      setShowIneligible(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    void run({ amount: +amount, purpose, termMonths: term ? +term : undefined, neededWithinDays: within ? +within : undefined });
  }

  const canApply = user?.role === "owner" || user?.role === "accountant";

  return (
    <>
      <PageHeader title="Financing" description="Compare lenders by real cost, fit and approval odds for your business profile." />

      <Card>
        <CardBody>
          <form onSubmit={submit} className="grid items-end gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_1fr_0.7fr_0.7fr_auto]">
            <label className="text-xs font-medium text-muted">Amount ({currency})
              <input type="number" min={1} step="any" required placeholder={currency === "USD" ? "e.g. 45000" : "e.g. 500000"}
                className={cn(inputClass, "num mt-1")} value={amount} onChange={(e) => setAmount(e.target.value)} />
            </label>
            <label className="text-xs font-medium text-muted">Purpose
              <select className={cn(inputClass, "mt-1")} value={purpose} onChange={(e) => setPurpose(e.target.value)}>
                {PURPOSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="text-xs font-medium text-muted">Term (months)
              <input type="number" min={1} max={120} placeholder="Any" className={cn(inputClass, "mt-1")} value={term} onChange={(e) => setTerm(e.target.value)} />
            </label>
            <label className="text-xs font-medium text-muted">Needed within (days)
              <input type="number" min={1} max={365} placeholder="Any" className={cn(inputClass, "mt-1")} value={within} onChange={(e) => setWithin(e.target.value)} />
            </label>
            <Button type="submit" disabled={busy}>
              {busy ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />} Compare
            </Button>
          </form>
          <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
            <Button size="sm" variant="secondary" onClick={() => run({ useForecast: true })} disabled={busy}>
              <Sparkles className="size-3.5" /> Size it from my cash-flow gap
            </Button>
            <span className="text-xs text-muted">Uses the forecast low point and safety buffer to size a bridge facility.</span>
          </div>
          {error && <p className="mt-3 text-sm text-danger" role="alert">{error}</p>}
        </CardBody>
      </Card>

      {!result && !busy && (
        <Card className="mt-6">
          <EmptyState icon={HandCoins} title="Find the right financing"
            description="Enter what you need, or let the copilot size a bridge from your cash-flow forecast. Every recommendation explains why." />
        </Card>
      )}

      {result?.message && <Card className="mt-6"><EmptyState icon={CheckCircle2} title="No financing needed" description={result.message} /></Card>}

      {result?.need && (
        <div className="mt-6 space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <span><b className="text-ink">{result.eligible.length}</b> eligible options for</span>
            <Badge tone="brand">{money(result.need.amount)}</Badge>
            <Badge tone="neutral">{result.need.purpose.replace("_", " ")}</Badge>
            {result.need.termMonths && <Badge tone="neutral">{result.need.termMonths} months</Badge>}
            {result.need.source === "forecast" && <Badge tone="info">sized from forecast gap</Badge>}
          </div>
          {result.fx && result.fx.length > 0 && (
            <p className="flex items-start gap-2 rounded-xl bg-info-soft px-3.5 py-2.5 text-xs text-info">
              <ArrowRightLeft className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                All amounts are in {result.currency}. Lender limits set in {result.fx.map((f) => f.from).join(", ")} were converted at{" "}
                {result.fx.map((f) => `1 ${f.from} = ${f.rate.toLocaleString("en-US", { maximumFractionDigits: 4 })} ${f.to}`).join(", ")} (indicative rate).
              </span>
            </p>
          )}

          {result.eligible.length === 0 && (
            <Card><EmptyState icon={XCircle} title="No eligible products" description="See the reasons below, or try a different amount or purpose." /></Card>
          )}
          {result.eligible.map((e) => (
            <OfferCard key={e.productId} e={e} weights={result.weights} canApply={canApply} purpose={result.need!.purpose} amount={result.need!.amount} />
          ))}

          <Card>
            <button className="flex w-full items-center gap-2 px-5 py-4 text-left text-sm font-medium text-ink" onClick={() => setShowIneligible((v) => !v)}
              aria-expanded={showIneligible}>
              <XCircle className="size-4 text-muted" />
              Not available to you ({result.ineligible.length}), and why
              <ChevronDown className={cn("ml-auto size-4 text-muted transition-transform", showIneligible && "rotate-180")} />
            </button>
            {showIneligible && (
              <CardBody className="divide-y divide-line border-t border-line pt-0">
                {result.ineligible.map((p) => (
                  <div key={p.productId} className="py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-ink">{p.lender} · {p.name}</p>
                      <Badge tone="neutral">{TYPE_LABEL[p.type] ?? p.type}</Badge>
                      {p.partialAmount && <Badge tone="info">could fund {money(p.partialAmount)} of it</Badge>}
                    </div>
                    <ul className="mt-1 space-y-0.5 text-xs text-muted">
                      {p.ineligibleReasons.map((r) => <li key={r}>• {r}</li>)}
                    </ul>
                  </div>
                ))}
              </CardBody>
            )}
          </Card>

          <CardHeader title="" subtitle={result.disclaimer} />
        </div>
      )}
    </>
  );
}
