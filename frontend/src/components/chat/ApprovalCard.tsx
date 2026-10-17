import { CheckCircle2, Clock, Loader2, ShieldCheck, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api, post } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { notifyApprovalsChanged } from "../../lib/events";
import { money } from "../../lib/format";
import { toast } from "../../lib/toast";
import type { ApprovalRequest } from "../../lib/types";
import { Badge, type Tone } from "../ui/Badge";
import { Button } from "../ui/Button";

const STATUS: Record<ApprovalRequest["status"], { tone: Tone; label: string }> = {
  pending: { tone: "warning", label: "Awaiting approval" },
  approved: { tone: "info", label: "Approved" },
  executed: { tone: "success", label: "Done" },
  rejected: { tone: "neutral", label: "Rejected" },
  expired: { tone: "neutral", label: "Expired" },
  failed: { tone: "danger", label: "Failed" },
};

const RISK: Record<ApprovalRequest["riskLevel"], Tone> = { low: "success", medium: "warning", high: "danger" };

/** Human-in-the-loop approval card. The agent can only create requests; a person decides here. */
export function ApprovalCard({ requestId, onChange }: { requestId: number; onChange?: (r: ApprovalRequest) => void }) {
  const { user } = useAuth();
  const [req, setReq] = useState<ApprovalRequest | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<ApprovalRequest>(`/approvals/${requestId}`).then(setReq).catch((e: Error) => setError(e.message));
  }, [requestId]);

  useEffect(load, [load]);

  async function decide(kind: "approve" | "reject") {
    setBusy(kind);
    setError(null);
    try {
      const updated = await post<ApprovalRequest>(`/approvals/${requestId}/${kind}`, {
        password: password || undefined,
        reason: kind === "reject" ? "Rejected from chat" : "",
      });
      setReq(updated);
      setPassword("");
      onChange?.(updated);
      notifyApprovalsChanged();
      if (kind === "reject") toast.info(`Request #${updated.id} rejected`);
      else if (updated.status === "failed") toast.error(`Request #${updated.id} approved, but it could not be completed`);
      else toast.success(`Request #${updated.id} approved`, updated.summary);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  if (!req) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-line p-3 text-xs text-muted">
        {error ?? <><Loader2 className="size-3.5 animate-spin" /> Loading request #{requestId}…</>}
      </div>
    );
  }

  const canDecide = req.status === "pending" && !!user && req.approverRoles.includes(user.role);
  const st = STATUS[req.status];

  return (
    <div className="overflow-hidden rounded-xl border border-warning/40 bg-warning-soft/40">
      <div className="flex flex-wrap items-center gap-2 border-b border-warning/20 px-4 py-2.5">
        <ShieldCheck className="size-4 text-warning" />
        <span className="text-xs font-semibold text-ink">Approval request #{req.id}</span>
        <Badge tone={RISK[req.riskLevel]}>{req.riskLevel} risk</Badge>
        <Badge tone={st.tone} className="ml-auto">{st.label}</Badge>
      </div>
      <div className="space-y-2 px-4 py-3">
        <p className="text-sm font-medium text-ink">{req.summary}</p>
        {req.rationale && <p className="text-xs text-muted">Why: {req.rationale}</p>}
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          {req.amount !== null && <span>Amount: <b className="num text-ink">{money(req.amount)}</b></span>}
          <span>Requested by: {req.requestedVia === "agent" ? "Copilot (on your behalf)" : "a team member"}</span>
          {req.status === "pending" && (
            <span className="flex items-center gap-1"><Clock className="size-3" />Expires {new Date(req.expiresAt).toLocaleString()}</span>
          )}
        </div>

        {req.result && (
          <p className={`flex items-start gap-1.5 text-xs ${req.status === "failed" ? "text-danger" : "text-success"}`}>
            {req.status === "failed" ? <XCircle className="mt-px size-3.5" /> : <CheckCircle2 className="mt-px size-3.5" />}
            {req.result.message}
          </p>
        )}

        {canDecide && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {req.requiresReauth && (
              <input
                type="password"
                autoComplete="current-password"
                placeholder="Confirm your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-surface px-2.5 text-xs text-ink focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none sm:max-w-52"
                aria-label="Password confirmation"
              />
            )}
            <Button size="sm" onClick={() => decide("approve")} disabled={!!busy || (req.requiresReauth && !password)}>
              {busy === "approve" ? <Loader2 className="size-3.5 animate-spin" /> : <CheckCircle2 className="size-3.5" />}
              Approve
            </Button>
            <Button size="sm" variant="secondary" onClick={() => decide("reject")} disabled={!!busy}>
              {busy === "reject" ? <Loader2 className="size-3.5 animate-spin" /> : <XCircle className="size-3.5" />}
              Reject
            </Button>
          </div>
        )}
        {req.status === "pending" && !canDecide && (
          <p className="text-xs text-muted">
            Needs approval by: {req.approverRoles.join(" or ")}.
          </p>
        )}
        {req.requiresReauth && canDecide && (
          <p className="text-[11px] text-muted">An amount this large needs your password to approve (limit shown in Settings).</p>
        )}
        {error && <p className="text-xs text-danger" role="alert">{error}</p>}
      </div>
    </div>
  );
}
