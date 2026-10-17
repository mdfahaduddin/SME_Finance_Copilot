import { FileCheck2, Inbox, Mail, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { ApprovalCard } from "../components/chat/ApprovalCard";
import { Badge } from "../components/ui/Badge";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { cn } from "../lib/cn";
import { money } from "../lib/format";
import type { ApprovalRequest } from "../lib/types";
import { useApi } from "../lib/useApi";

type Filter = "pending" | "executed" | "rejected" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "pending", label: "Pending" },
  { key: "executed", label: "Done" },
  { key: "rejected", label: "Rejected" },
  { key: "all", label: "All" },
];

interface OutboxMessage {
  id: number; actionRequestId: number | null; recipient: string; subject: string; body: string; createdAt: string;
}
interface LoanApplication {
  id: number; amount: number; termMonths: number; purpose: string; status: string; referenceNo: string; submittedAt: string | null;
}

export default function Approvals() {
  const [filter, setFilter] = useState<Filter>("pending");
  const { data, loading, error, reload } = useApi<ApprovalRequest[]>(`/approvals?status=${filter}`);
  const { data: outbox, reload: reloadOutbox } = useApi<OutboxMessage[]>("/ledger/outbox");
  const { data: apps, reload: reloadApps } = useApi<LoanApplication[]>("/ledger/loan-applications");
  const [openMsg, setOpenMsg] = useState<number | null>(null);

  function refreshAll() {
    void reload();
    void reloadOutbox();
    void reloadApps();
  }

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Every action with a real-world effect waits here for a human decision. The copilot can request, never approve."
      />

      <div className="grid gap-6 xl:grid-cols-5">
        <div className="min-w-0 space-y-4 xl:col-span-3">
          <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1" role="tablist">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                role="tab"
                aria-selected={filter === f.key}
                onClick={() => setFilter(f.key)}
                className={cn(
                  "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  filter === f.key ? "bg-brand-600 text-white shadow-sm" : "text-muted hover:bg-surface-2 hover:text-ink",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>

          {error && <Card><EmptyState icon={ShieldCheck} title="Unable to load requests" description={error} /></Card>}
          {loading && !data && <Skeleton className="h-40" />}
          {data && data.length === 0 && (
            <Card>
              <EmptyState icon={Inbox} title={filter === "pending" ? "Nothing waiting for approval" : "No requests here"}
                description="Ask the copilot to chase an invoice or apply for financing; its requests appear here." />
            </Card>
          )}
          {/* key includes the filter so cards refetch when the list changes */}
          {data?.map((r) => <ApprovalCard key={`${filter}-${r.id}`} requestId={r.id} onChange={refreshAll} />)}
        </div>

        <div className="min-w-0 space-y-4 xl:col-span-2">
          <Card>
            <CardHeader title="Sent messages" subtitle="Prepared messages. Nothing is emailed automatically: copy and send them yourself" />
            <CardBody className="pt-3">
              {!outbox?.length && <p className="text-sm text-muted">No messages sent yet.</p>}
              <ul className="divide-y divide-line">
                {outbox?.map((m) => (
                  <li key={m.id} className="py-2.5">
                    <button className="flex w-full items-start gap-2 text-left" onClick={() => setOpenMsg(openMsg === m.id ? null : m.id)}
                      aria-expanded={openMsg === m.id}>
                      <Mail className="mt-0.5 size-4 shrink-0 text-muted" />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-ink">{m.subject}</span>
                        <span className="block truncate text-xs text-muted">To {m.recipient} · {new Date(m.createdAt).toLocaleString()}</span>
                      </span>
                      {m.actionRequestId && <Badge tone="neutral">#{m.actionRequestId}</Badge>}
                    </button>
                    {openMsg === m.id && (
                      <pre className="mt-2 rounded-lg bg-surface-2 p-3 font-sans text-xs whitespace-pre-wrap text-ink">{m.body}</pre>
                    )}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title="Financing applications" subtitle="Application packs prepared for lenders. Lenders are not contacted automatically" />
            <CardBody className="pt-3">
              {!apps?.length && <p className="text-sm text-muted">No applications yet.</p>}
              <ul className="divide-y divide-line">
                {apps?.map((a) => (
                  <li key={a.id} className="flex items-start gap-2 py-2.5">
                    <FileCheck2 className="mt-0.5 size-4 shrink-0 text-success" />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-ink">{money(a.amount)} · {a.termMonths} months</p>
                      <p className="truncate text-xs text-muted">{a.purpose} · Ref {a.referenceNo}</p>
                    </div>
                    <Badge tone="info">{a.status === "submitted" ? "under review" : a.status}</Badge>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
