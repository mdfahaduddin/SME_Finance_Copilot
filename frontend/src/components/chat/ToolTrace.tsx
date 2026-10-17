import { Check, ChevronDown, CircleSlash, Clock, Loader2, Wrench } from "lucide-react";
import { useState } from "react";
import { cn } from "../../lib/cn";
import type { Tier, ToolTraceEntry } from "../../lib/types";
import { Badge, type Tone } from "../ui/Badge";

export const TOOL_LABELS: Record<string, string> = {
  get_business_profile: "Read business profile",
  get_account_balances: "Read account balances",
  get_invoices: "Read invoices",
  get_bills: "Read supplier bills",
  get_transactions: "Read transactions",
  get_alerts: "Check alerts",
  analyze_financials: "Analyse financials",
  forecast_cashflow: "Forecast cash flow",
  match_financing: "Match financing",
  run_scenario: "Run what-if scenario",
  explain_metric: "Explain metric",
  request_payment_reminder: "Request payment reminder",
  request_schedule_payment: "Request payment",
  request_bill_deferral: "Request bill deferral",
  request_loan_application: "Request loan application",
};

const TIER: Record<Tier, { label: string; tone: Tone }> = {
  T0: { label: "Read", tone: "neutral" },
  T1: { label: "Advisory", tone: "info" },
  T2: { label: "Action", tone: "warning" },
  "?": { label: "Unknown", tone: "danger" },
};

const DECISION: Record<ToolTraceEntry["decision"], { label: string; tone: Tone }> = {
  allowed: { label: "done", tone: "success" },
  pending_approval: { label: "needs approval", tone: "warning" },
  denied: { label: "blocked", tone: "danger" },
  refused: { label: "refused", tone: "danger" },
  error: { label: "error", tone: "danger" },
};

export function TierBadge({ tier }: { tier: Tier }) {
  return <Badge tone={TIER[tier].tone} className="font-mono">{tier} · {TIER[tier].label}</Badge>;
}

/** Live list of tools while the agent is working. */
export function LiveTools({ tools }: { tools: { id: string; name: string; tier: Tier; done: boolean }[] }) {
  return (
    <ul className="space-y-1.5">
      {tools.map((t) => (
        <li key={t.id} className="flex items-center gap-2 text-xs text-muted">
          {t.done ? <Check className="size-3.5 text-success" /> : <Loader2 className="size-3.5 animate-spin text-brand-500" />}
          <span className="text-ink">{TOOL_LABELS[t.name] ?? t.name}</span>
          <TierBadge tier={t.tier} />
        </li>
      ))}
    </ul>
  );
}

/** Collapsible record of every tool the agent used for an answer. */
export function ToolTrace({ trace }: { trace: ToolTraceEntry[] }) {
  const [open, setOpen] = useState(false);
  if (!trace.length) return null;
  const blocked = trace.filter((t) => ["denied", "refused", "error"].includes(t.decision)).length;
  return (
    <div className="rounded-xl border border-line bg-surface-2/50">
      <button
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-muted hover:text-ink"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <Wrench className="size-3.5" />
        {trace.length} tool {trace.length === 1 ? "call" : "calls"}
        {blocked > 0 && <Badge tone="danger">{blocked} blocked</Badge>}
        <ChevronDown className={cn("ml-auto size-4 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <ol className="space-y-2 border-t border-line px-3 py-3">
          {trace.map((t, i) => (
            <li key={t.id + i} className="flex gap-3">
              <span className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-surface text-[10px] font-semibold text-muted ring-1 ring-line">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs font-medium text-ink">{TOOL_LABELS[t.name] ?? t.name}</span>
                  <TierBadge tier={t.tier} />
                  <Badge tone={DECISION[t.decision].tone}>
                    {t.decision === "allowed" ? <Check className="size-3" /> : <CircleSlash className="size-3" />}
                    {DECISION[t.decision].label}
                  </Badge>
                  <span className="ml-auto flex items-center gap-1 text-[11px] text-muted">
                    <Clock className="size-3" />{t.ms} ms
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-muted">{t.summary}</p>
                {Object.keys(t.args).length > 0 && (
                  <code className="mt-1 block truncate font-mono text-[11px] text-muted" title={JSON.stringify(t.args)}>
                    {t.name}({JSON.stringify(t.args)})
                  </code>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
