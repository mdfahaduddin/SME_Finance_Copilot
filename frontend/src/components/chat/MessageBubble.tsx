import { AlertTriangle, Bot, Check, Copy, EyeOff, ShieldCheck, WifiOff } from "lucide-react";
import { useState } from "react";
import { Markdown } from "../../lib/markdown";
import type { ChatMessage } from "../../lib/types";
import { Badge } from "../ui/Badge";
import { ApprovalCard } from "./ApprovalCard";
import { LiveTools, ToolTrace } from "./ToolTrace";

function clock(iso?: string) {
  const d = iso ? new Date(iso) : new Date();
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function TrustBar({ m }: { m: ChatMessage }) {
  const g = m.groundedness;
  return (
    <>
      {g && g.checked > 0 && (g.unverified.length === 0 ? (
        <Badge tone="success">
          <span title="Every figure in this answer matches a result from the finance engines" className="flex items-center gap-1">
            <ShieldCheck className="size-3" /> {g.grounded}/{g.checked} figures verified
          </span>
        </Badge>
      ) : (
        <Badge tone="warning">
          <span title={`Not found in tool results: ${g.unverified.join(", ")}`} className="flex items-center gap-1">
            <AlertTriangle className="size-3" /> {g.unverified.length} unverified figure{g.unverified.length > 1 ? "s" : ""}
          </span>
        </Badge>
      ))}
      {!!m.piiMasked && (
        <Badge tone="neutral">
          <span title="Names, emails and account numbers were replaced with tokens before reaching the AI model" className="flex items-center gap-1">
            <EyeOff className="size-3" /> {m.piiMasked} hidden from AI
          </span>
        </Badge>
      )}
      {m.mode === "offline" && <Badge tone="warning"><WifiOff className="size-3" /> offline mode</Badge>}
    </>
  );
}

function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard blocked */
        }
      }}
      className="grid size-7 place-items-center rounded-md text-muted transition-colors hover:bg-surface-2 hover:text-ink"
      aria-label={done ? "Copied" : "Copy answer"}
      title={done ? "Copied" : "Copy answer"}
    >
      {done ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
    </button>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1" aria-label="Copilot is thinking">
      {[0, 150, 300].map((d) => (
        <span key={d} className="size-1.5 animate-bounce rounded-full bg-brand-500" style={{ animationDelay: `${d}ms` }} />
      ))}
    </span>
  );
}

export function MessageBubble({ m }: { m: ChatMessage & { createdAt?: string } }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-brand-500 to-brand-700 px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap text-white shadow-md shadow-brand-600/20">
          {m.content}
        </div>
      </div>
    );
  }

  const approvals = m.approvalRequests ?? m.toolTrace.flatMap((t) => (t.approvalRequestId ? [t.approvalRequestId] : []));
  const working = m.pending && !m.content;

  return (
    <div className="flex gap-3 sm:gap-4">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-sm">
        <Bot className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex items-center gap-2">
          <span className="text-sm font-semibold text-ink">Copilot</span>
          <span className="text-xs text-muted">{clock(m.createdAt)}</span>
        </div>

        {working && (
          <div className="inline-flex min-w-64 flex-col gap-2.5 rounded-2xl border border-line bg-surface px-4 py-3 shadow-card">
            <div className="flex items-center gap-2.5 text-sm text-muted">
              <TypingDots />
              <span>{m.status && m.status !== "Thinking..." ? m.status : m.liveTools?.length ? "Working on it" : "Thinking"}</span>
            </div>
            {m.liveTools && m.liveTools.length > 0 && <LiveTools tools={m.liveTools} />}
          </div>
        )}

        {m.content && (
          <div className="text-[15px] leading-7 text-ink/90">
            <Markdown text={m.content} />
            {m.pending && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-brand-500 align-middle" />}
          </div>
        )}

        {m.error && (
          <p className="mt-2 rounded-xl bg-danger-soft px-3 py-2 text-sm text-danger" role="alert">{m.error}</p>
        )}

        {!m.pending && approvals.length > 0 && (
          <div className="mt-4 space-y-3">{approvals.map((id) => <ApprovalCard key={id} requestId={id} />)}</div>
        )}

        {!m.pending && m.content && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <TrustBar m={m} />
              <span className="ml-auto"><CopyButton text={m.content} /></span>
            </div>
            <ToolTrace trace={m.toolTrace} />
          </div>
        )}
      </div>
    </div>
  );
}
