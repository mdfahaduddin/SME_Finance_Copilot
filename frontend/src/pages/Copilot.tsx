import { CornerDownRight, History, MessageSquarePlus, ShieldCheck, Sparkles } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Composer } from "../components/chat/Composer";
import { ConversationList } from "../components/chat/ConversationList";
import { EmptyChat } from "../components/chat/EmptyChat";
import { MessageBubble } from "../components/chat/MessageBubble";
import { api, del, patch, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cn } from "../lib/cn";
import { notifyApprovalsChanged } from "../lib/events";
import { streamChat } from "../lib/sse";
import { errorText, toast } from "../lib/toast";
import type { ChatEvent, ChatMessage, ChatSession } from "../lib/types";
import { useApi } from "../lib/useApi";

interface Policy { agent: { mode: "online" | "offline"; model: string | null } }

// Follow-up prompts suggested after an answer, based on the tools the copilot just used.
const FOLLOW_UPS: Record<string, string[]> = {
  forecast_cashflow: ["What's driving the lowest week?", "How can I close the cash gap?"],
  run_scenario: ["What financing would make this affordable?", "What if I delay it by a month?"],
  match_financing: ["Explain why the top option ranks first", "Which options am I not eligible for, and why?"],
  get_invoices: ["Which customers pay late most often?", "What happens to cash if they pay 30 days late?"],
  analyze_financials: ["How do I improve my weakest area?", "Show my biggest expense changes"],
  get_alerts: ["Which alert should I handle first?", "Will I run out of cash in the next 3 months?"],
};
const DEFAULT_FOLLOW_UPS = ["Will I run out of cash in the next 3 months?", "What should I focus on this month?"];

let localId = 0;

export default function Copilot() {
  const { user } = useAuth();
  const { data: policy } = useApi<Policy>("/policy");
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const loadSessions = useCallback(() => api<ChatSession[]>("/chat/sessions").then(setSessions).catch(() => {}), []);
  useEffect(() => void loadSessions(), [loadSessions]);

  // Keep the newest content in view while streaming.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  async function openSession(id: number) {
    if (busy) return;
    setActiveId(id);
    setDrawer(false);
    setMessages(await api<ChatMessage[]>(`/chat/sessions/${id}/messages`));
  }

  async function pinSession(id: number, pinned: boolean) {
    try {
      await patch<ChatSession>(`/chat/sessions/${id}`, { pinned });
      toast.success(pinned ? "Pinned to the top" : "Unpinned");
      await loadSessions();  // the order changes
    } catch (e) {
      toast.error(`Could not ${pinned ? "pin" : "unpin"} the conversation`, errorText(e));
    }
  }

  async function renameSession(id: number, title: string) {
    try {
      const updated = await patch<ChatSession>(`/chat/sessions/${id}`, { title });
      setSessions((list) => list.map((x) => (x.id === id ? { ...x, title: updated.title } : x)));
      toast.success("Conversation renamed");
    } catch (e) {
      toast.error("Could not rename the conversation", errorText(e));
      throw e;
    }
  }

  async function deleteSession(id: number) {
    try {
      await del(`/chat/sessions/${id}`);
      if (id === activeId) {
        setActiveId(null);
        setMessages([]);
      }
      toast.success("Conversation deleted");
      await loadSessions();
    } catch (e) {
      toast.error("Could not delete the conversation", errorText(e));
    }
  }

  function newChat() {
    if (busy) return;
    setActiveId(null);
    setMessages([]);
    setDrawer(false);
    inputRef.current?.focus();
  }

  const patchPending = (fn: (m: ChatMessage) => ChatMessage) =>
    setMessages((ms) => ms.map((m) => (m.pending ? fn(m) : m)));

  function handleEvent(e: ChatEvent) {
    switch (e.type) {
      case "status":
        patchPending((m) => ({ ...m, status: e.text }));
        break;
      case "reset":
        patchPending((m) => ({ ...m, content: "", liveTools: [] }));
        break;
      case "delta":
        patchPending((m) => ({ ...m, content: m.content + e.text }));
        break;
      case "tool_call":
        patchPending((m) => ({ ...m, liveTools: [...(m.liveTools ?? []), { id: e.id, name: e.name, tier: e.tier, done: false }] }));
        break;
      case "tool_result":
        patchPending((m) => ({ ...m, liveTools: (m.liveTools ?? []).map((t) => (t.id === e.id ? { ...t, done: true } : t)) }));
        break;
      case "final":
        if (e.approvalRequests.length) notifyApprovalsChanged();
        patchPending((m) => ({
          id: e.messageId, role: "assistant", content: e.content, toolTrace: e.toolTrace, mode: e.mode,
          groundedness: e.groundedness, approvalRequests: e.approvalRequests, piiMasked: e.piiMasked, createdAt: m.createdAt,
        }));
        break;
      case "error":
        patchPending((m) => ({ ...m, pending: false, error: e.message }));
        break;
    }
  }

  async function send(text: string) {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    let sessionId = activeId;
    const now = new Date().toISOString();
    try {
      if (sessionId === null) {
        const s = await post<ChatSession>("/chat/sessions", {});
        sessionId = s.id;
        setActiveId(s.id);
      }
      setMessages((ms) => [
        ...ms,
        { id: `u${++localId}`, role: "user", content, toolTrace: [], createdAt: now },
        { id: `a${++localId}`, role: "assistant", content: "", toolTrace: [], pending: true, liveTools: [], createdAt: now },
      ]);
      abortRef.current = new AbortController();
      await streamChat(sessionId, content, handleEvent, abortRef.current.signal);
    } catch (err) {
      const aborted = err instanceof DOMException && err.name === "AbortError";
      patchPending((m) => ({ ...m, pending: false, error: aborted ? "Stopped." : err instanceof Error ? err.message : String(err) }));
    } finally {
      patchPending((m) => ({ ...m, pending: false }));
      abortRef.current = null;
      setBusy(false);
      void loadSessions();
      inputRef.current?.focus();
    }
  }

  const last = messages[messages.length - 1];
  const asked = new Set(messages.filter((m) => m.role === "user").map((m) => m.content.trim().toLowerCase()));
  const followUps = !busy && last?.role === "assistant" && last.content && !last.error
    ? (last.toolTrace.map((t) => FOLLOW_UPS[t.name]).find(Boolean) ?? DEFAULT_FOLLOW_UPS)
        .filter((f) => !asked.has(f.toLowerCase()))
    : [];
  const title = sessions.find((s) => s.id === activeId)?.title ?? "New conversation";
  const online = policy?.agent.mode === "online";

  return (
    <div className="flex h-[calc(100dvh-4rem)]">
      {/* Conversation history: column on wide screens */}
      <aside className="hidden w-80 shrink-0 border-r border-line bg-surface xl:block">
        <ConversationList sessions={sessions} activeId={activeId} disabled={busy} onSelect={openSession} onNew={newChat} onPin={pinSession} onRename={renameSession} onDelete={deleteSession} />
      </aside>

      {/* ...and a drawer below xl */}
      {drawer && (
        <div className="fixed inset-0 z-30 xl:hidden" role="dialog" aria-modal="true" aria-label="Conversations">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px]" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 right-0 w-80 max-w-[85vw] bg-surface shadow-xl">
            <ConversationList sessions={sessions} activeId={activeId} disabled={busy} onSelect={openSession} onNew={newChat} onPin={pinSession} onRename={renameSession} onDelete={deleteSession}
              onClose={() => setDrawer(false)} />
          </div>
        </div>
      )}

      <section className="relative flex min-w-0 flex-1 flex-col bg-canvas">
        {/* Soft brand glow behind the conversation */}
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-[radial-gradient(ellipse_at_top,var(--color-brand-100),transparent_70%)] opacity-70 dark:bg-[radial-gradient(ellipse_at_top,var(--color-brand-900),transparent_70%)] dark:opacity-40" />

        {/* Chat header */}
        <header className="relative z-10 flex h-16 shrink-0 items-center gap-3 border-b border-line bg-surface/80 px-4 backdrop-blur sm:px-6">
          <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 text-white shadow-sm shadow-brand-600/30">
            <Sparkles className="size-4.5" />
          </span>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold text-ink">{title}</h1>
            <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
              <span className="relative flex size-2">
                {online && <span className="absolute inline-flex size-full animate-ping rounded-full bg-success opacity-50 motion-reduce:hidden" />}
                <span className={cn("relative inline-flex size-2 rounded-full", online ? "bg-success" : "bg-warning")} />
              </span>
              <span className="truncate">
                {policy ? (online ? `Online · ${policy.agent.model}` : "Offline mode · rule-based answers") : "Finance Copilot"}
              </span>
            </p>
          </div>
          <button onClick={newChat} disabled={busy || messages.length === 0}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-xs font-medium text-ink transition-colors hover:bg-surface-2 disabled:opacity-50 xl:hidden">
            <MessageSquarePlus className="size-4" /><span className="hidden sm:inline">New chat</span>
          </button>
          <button onClick={() => setDrawer(true)}
            className="flex h-9 items-center gap-1.5 rounded-lg border border-line bg-surface px-3 text-xs font-medium text-ink transition-colors hover:bg-surface-2 xl:hidden"
            aria-label="Show conversations">
            <History className="size-4" /><span className="hidden sm:inline">History</span>
          </button>
        </header>

        {/* Messages */}
        <div ref={scrollRef} className="relative min-h-0 flex-1 overflow-y-auto">
          <div className={cn("mx-auto w-full max-w-3xl px-4 sm:px-6", messages.length ? "space-y-8 py-8" : "h-full")}>
            {messages.length === 0
              ? <EmptyChat name={user?.name.split(" ")[0]} onPick={send} />
              : messages.map((m) => <MessageBubble key={m.id} m={m} />)}

            {followUps.length > 0 && (
              <div className="pl-11 sm:pl-12">
                <p className="mb-2 text-xs font-medium text-muted">Ask next</p>
                <div className="flex flex-wrap gap-2">
                  {followUps.map((f) => (
                    <button key={f} onClick={() => send(f)}
                      className="flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-ink shadow-sm transition-colors hover:border-brand-300 hover:bg-brand-50 dark:hover:border-brand-700 dark:hover:bg-brand-900/30">
                      <CornerDownRight className="size-3 text-brand-500" />{f}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Composer: content fades out underneath it */}
        <div className="relative shrink-0 px-4 pb-4 sm:px-6">
          <div aria-hidden className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-gradient-to-t from-canvas to-transparent" />
          <div className="mx-auto max-w-3xl">
            <Composer
              ref={inputRef}
              value={input}
              busy={busy}
              readOnly={user?.role === "viewer"}
              onChange={setInput}
              onSend={() => send(input)}
              onStop={() => abortRef.current?.abort()}
            />
            <p className="mt-2 flex items-center justify-center gap-1.5 text-center text-[11px] text-muted">
              <ShieldCheck className="size-3 shrink-0 text-success" aria-hidden />
              {user?.role === "viewer"
                ? "Read-only access: the copilot can analyse, but not request actions."
                : "Figures come from your ledger. Actions always wait for your approval."}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
