import { Bot, ChevronDown, Download, Link2, Loader2, Lock, RefreshCw, ScrollText, ServerCog, ShieldAlert, ShieldCheck, User } from "lucide-react";
import { Fragment, useState } from "react";
import { Badge, type Tone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { downloadFile } from "../lib/download";
import { errorText, toast } from "../lib/toast";
import { useApi } from "../lib/useApi";

interface AuditRow {
  id: number; ts: string; actor: string; actorType: "user" | "agent" | "system"; action: string; tool: string;
  tier: string; paramsHash: string; result: string; decision: string; prevHash: string; hash: string;
}
interface ChainStatus { valid: boolean; records: number; brokenAtId: number | null; reason?: string; headHash?: string; verifiedAt?: string }

const ACTOR = {
  user: { icon: User, label: "User", tone: "info" as Tone },
  agent: { icon: Bot, label: "Agent", tone: "brand" as Tone },
  system: { icon: ServerCog, label: "System", tone: "neutral" as Tone },
};

const DECISION_TONE: Record<string, Tone> = {
  allowed: "success", approved: "success", executed: "success", online: "success",
  pending: "warning", pending_approval: "warning", flagged: "warning", fallback: "warning", offline: "warning",
  denied: "danger", refused: "danger", rejected: "danger", failed: "danger", error: "danger", expired: "neutral",
};

type ActorFilter = "" | "user" | "agent" | "system";

export default function Audit() {
  const { user } = useAuth();
  const [actor, setActor] = useState<ActorFilter>("");
  const [open, setOpen] = useState<number | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const staff = user?.role !== "viewer";
  const { data, loading, error, reload } = useApi<{ items: AuditRow[] }>(staff ? `/audit?limit=300${actor ? `&actorType=${actor}` : ""}` : null);
  const chain = useApi<ChainStatus>(staff ? "/audit/verify" : null);

  if (!staff) {
    return (
      <>
        <PageHeader title="Audit Log" />
        <Card><EmptyState icon={Lock} title="Restricted" description="The audit log is available to owners and accountants." /></Card>
      </>
    );
  }

  async function exportAs(format: "json" | "csv") {
    setDownloading(format);
    try {
      await downloadFile(`/audit/export?format=${format}`, `audit-log.${format}`);
      toast.success("Audit log exported", `Saved as audit-log.${format}`);
    } catch (err) {
      toast.error("Export failed", errorText(err));
    } finally {
      setDownloading(null);
      void reload();
      void chain.reload();
    }
  }

  const c = chain.data;

  return (
    <>
      <PageHeader
        title="Audit Log"
        description="Append-only record of every login, agent tool call and decision. Each entry is hash-linked to the previous one."
        actions={
          <>
            <Button size="sm" variant="secondary" onClick={() => exportAs("csv")} disabled={!!downloading}>
              {downloading === "csv" ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />} CSV
            </Button>
            <Button size="sm" variant="secondary" onClick={() => exportAs("json")} disabled={!!downloading}>
              {downloading === "json" ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />} JSON + proof
            </Button>
          </>
        }
      />

      {/* Chain integrity */}
      <Card className={cn("mb-6 border-l-4", c ? (c.valid ? "border-l-success" : "border-l-danger") : "border-l-line")}>
        <CardBody className="flex flex-wrap items-center gap-4">
          {c?.valid ? <ShieldCheck className="size-8 text-success" /> : c ? <ShieldAlert className="size-8 text-danger" /> : <Loader2 className="size-8 animate-spin text-muted" />}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-ink">
              {!c ? "Verifying hash chain…" : c.valid ? "Hash chain intact" : `Tampering detected at record #${c.brokenAtId}`}
            </p>
            <p className="text-xs text-muted">
              {c?.valid
                ? <>All {c.records} records re-hashed and linked. Head: <code className="font-mono">{c.headHash?.slice(0, 16)}…</code></>
                : c ? c.reason : "Recomputing SHA-256 for every record"}
            </p>
          </div>
          <Button size="sm" variant="ghost" onClick={() => chain.reload()}><RefreshCw className="size-3.5" /> Verify again</Button>
        </CardBody>
      </Card>

      <div className="mb-4 flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1">
        {(["", "user", "agent", "system"] as ActorFilter[]).map((a) => (
          <button key={a || "all"} onClick={() => setActor(a)} aria-pressed={actor === a}
            className={cn("rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              actor === a ? "bg-brand-600 text-white shadow-sm" : "text-muted hover:bg-surface-2 hover:text-ink")}>
            {a ? ACTOR[a].label : "All"}
          </button>
        ))}
      </div>

      {error && <Card><EmptyState icon={ScrollText} title="Unable to load the audit log" description={error} /></Card>}
      {loading && !data && <Skeleton className="h-96" />}
      {data && (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm">
              <thead className="bg-surface-2/60 text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">#</th>
                  <th className="px-4 py-2.5 font-medium">Time (UTC)</th>
                  <th className="px-4 py-2.5 font-medium">Actor</th>
                  <th className="px-4 py-2.5 font-medium">Action</th>
                  <th className="px-4 py-2.5 font-medium">Decision</th>
                  <th className="px-4 py-2.5 font-medium">Detail</th>
                  <th className="w-8" />
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 && (
                  <tr><td colSpan={7} className="px-4 py-10 text-center text-muted">No records.</td></tr>
                )}
                {data.items.map((r) => {
                  const A = ACTOR[r.actorType];
                  const isOpen = open === r.id;
                  return (
                    <Fragment key={r.id}>
                      <tr className={cn("cursor-pointer border-t border-line align-top hover:bg-surface-2/60", isOpen && "bg-surface-2/60")}
                        onClick={() => setOpen(isOpen ? null : r.id)}>
                        <td className="num px-4 py-2.5 text-xs text-muted">{r.id}</td>
                        <td className="num px-4 py-2.5 text-xs whitespace-nowrap text-muted">{r.ts.replace("T", " ").replace("Z", "")}</td>
                        <td className="px-4 py-2.5">
                          <Badge tone={A.tone}><A.icon className="size-3" />{A.label}</Badge>
                          <p className="mt-1 max-w-48 truncate text-xs text-muted" title={r.actor}>{r.actor}</p>
                        </td>
                        <td className="px-4 py-2.5">
                          <p className="font-mono text-xs text-ink">{r.action}</p>
                          {r.tool && <p className="mt-0.5 text-xs text-muted">{r.tool}{r.tier && ` · ${r.tier}`}</p>}
                        </td>
                        <td className="px-4 py-2.5">{r.decision && <Badge tone={DECISION_TONE[r.decision] ?? "neutral"}>{r.decision}</Badge>}</td>
                        <td className="max-w-md px-4 py-2.5 text-xs text-muted"><p className="line-clamp-2">{r.result}</p></td>
                        <td className="px-2 py-2.5"><ChevronDown className={cn("size-4 text-muted transition-transform", isOpen && "rotate-180")} /></td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-surface-2/60">
                          <td colSpan={7} className="px-4 pb-4">
                            <p className="mb-2 text-xs text-ink">{r.result}</p>
                            <dl className="grid gap-1 font-mono text-[11px] text-muted sm:grid-cols-[8rem_1fr]">
                              <dt>Hash</dt><dd className="break-all text-ink">{r.hash}</dd>
                              <dt className="flex items-center gap-1"><Link2 className="size-3" />Previous</dt><dd className="break-all">{r.prevHash}</dd>
                              {r.paramsHash && <><dt>Params hash</dt><dd className="break-all">{r.paramsHash}</dd></>}
                            </dl>
                            <p className="mt-2 text-[11px] text-muted">Parameters are stored only as a hash, so the log proves what was used without keeping personal data.</p>
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
      )}
    </>
  );
}
