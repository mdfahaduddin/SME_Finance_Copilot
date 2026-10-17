import { Check, Loader2, MessageSquarePlus, MessagesSquare, Pencil, Pin, PinOff, Search, SearchX, ShieldCheck, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import type { ChatSession } from "../../lib/types";

export function timeAgo(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Today / Yesterday / Previous 7 days / Previous 30 days / Older, by last activity (local time). */
function groupOf(iso: string): string {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.floor((today.getTime() - new Date(iso).getTime()) / 86_400_000) + 1;
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days <= 7) return "Previous 7 days";
  if (days <= 30) return "Previous 30 days";
  return "Older";
}

/** Wraps case-insensitive matches of `term` in <mark>. */
function highlight(text: string, term: string): ReactNode {
  if (!term) return text;
  const lower = text.toLowerCase();
  const t = term.toLowerCase();
  const out: ReactNode[] = [];
  let at = 0;
  for (let i = lower.indexOf(t); i !== -1; i = lower.indexOf(t, at)) {
    out.push(text.slice(at, i), <mark key={i} className="rounded-sm bg-brand-100 text-brand-800 dark:bg-brand-800/60 dark:text-brand-100">{text.slice(i, i + t.length)}</mark>);
    at = i + t.length;
  }
  out.push(text.slice(at));
  return out;
}

/** Server-side search (titles and message text), debounced. Re-runs when the list changes (e.g. after a reply). */
function useSearch(term: string, version: unknown) {
  const [results, setResults] = useState<ChatSession[] | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!term) {
      setResults(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    const t = setTimeout(() => {
      api<ChatSession[]>(`/chat/sessions?q=${encodeURIComponent(term)}`)
        .then((r) => alive && setResults(r))
        .catch(() => alive && setResults([]))
        .finally(() => alive && setLoading(false));
    }, 250);
    return () => { alive = false; clearTimeout(t); };
  }, [term, version]);
  return { results, loading };
}

interface Props {
  sessions: ChatSession[];
  activeId: number | null;
  disabled?: boolean;
  onSelect: (id: number) => void;
  onNew: () => void;
  /** Pins or unpins a conversation (pinned ones are listed first). */
  onPin: (id: number, pinned: boolean) => Promise<void>;
  /** Renames a conversation; resolves when saved. */
  onRename: (id: number, title: string) => Promise<void>;
  /** Deletes a conversation; resolves when done (the row asks for confirmation first). */
  onDelete: (id: number) => Promise<void>;
  /** When shown as a drawer: renders a close button in the header row. */
  onClose?: () => void;
}

/** Conversation history panel (desktop column, mobile drawer) with search. */
export function ConversationList({ sessions, activeId, disabled, onSelect, onNew, onPin, onRename, onDelete, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [editing, setEditing] = useState<{ id: number; value: string } | null>(null);
  const [saving, setSaving] = useState(false);

  async function saveRename() {
    if (!editing || saving) return;
    const title = editing.value.replace(/\s+/g, " ").trim();
    const current = list.find((x) => x.id === editing.id)?.title;
    if (!title || title === current) {  // empty or unchanged: nothing to save
      setEditing(null);
      return;
    }
    setSaving(true);
    try {
      await onRename(editing.id, title);
      setEditing(null);
    } catch {
      /* the page shows the error; keep the field open so the name isn't lost */
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: number) {
    setDeleting(true);
    try {
      await onDelete(id);
    } finally {
      setDeleting(false);
      setConfirming(null);
    }
  }
  const term = query.trim().replace(/\s+/g, " ");
  const { results, loading } = useSearch(term, sessions);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const list = term ? results ?? [] : sessions;

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-3 px-4 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <h2 className="flex-1 text-sm font-semibold text-ink">
            Conversations {sessions.length > 0 && <span className="ml-1 font-normal text-muted">{sessions.length}</span>}
          </h2>
          {onClose && (
            <button onClick={onClose} aria-label="Close conversations"
              className="grid size-8 place-items-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-ink">
              <X className="size-4" />
            </button>
          )}
        </div>
        <button onClick={onNew} disabled={disabled}
          className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-brand-600 text-sm font-medium text-white shadow-sm shadow-brand-600/20 transition-colors hover:bg-brand-700 disabled:opacity-60">
          <MessageSquarePlus className="size-4" /> New chat
        </button>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <input ref={searchRef} type="search" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={100}
            onKeyDown={(e) => { if (e.key === "Escape" && query) { e.preventDefault(); setQuery(""); } }}
            placeholder="Search conversations" aria-label="Search conversations"
            className="h-9 w-full rounded-lg border border-line bg-surface-2/60 pr-9 pl-9 text-sm text-ink placeholder:text-muted focus:border-brand-500 focus:bg-surface focus:ring-2 focus:ring-brand-500/20 focus:outline-none [&::-webkit-search-cancel-button]:hidden" />
          {loading ? (
            <Loader2 className="absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin text-muted" aria-label="Searching" />
          ) : query && (
            <button onClick={() => { setQuery(""); searchRef.current?.focus(); }} aria-label="Clear search"
              className="absolute top-1/2 right-1.5 grid size-6 -translate-y-1/2 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </div>

      <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-2" aria-label="Conversations">
        {term && results && results.length > 0 && (
          <p className="px-3 pb-2 text-xs text-muted" role="status">
            {results.length}{results.length === 50 && "+"} {results.length === 1 ? "match" : "matches"}
          </p>
        )}
        {list.length === 0 && !loading && (
          term ? (
            <div className="flex flex-col items-center px-4 py-10 text-center">
              <SearchX className="size-8 text-muted/60" aria-hidden />
              <p className="mt-3 text-sm font-medium text-ink">No conversations found</p>
              <p className="mt-1 text-xs text-muted">Nothing matches “{term}”. Try another word.</p>
            </div>
          ) : (
            <div className="flex flex-col items-center px-4 py-10 text-center">
              <MessagesSquare className="size-8 text-muted/60" aria-hidden />
              <p className="mt-3 text-sm font-medium text-ink">No conversations yet</p>
              <p className="mt-1 text-xs text-muted">Ask your first question to get started.</p>
            </div>
          )
        )}
        {list.map((s, i) => {
          const active = s.id === activeId;
          const groupFor = (x: ChatSession) => (x.pinned ? "Pinned" : groupOf(x.lastMessageAt));
          const group = groupFor(s);
          const showGroup = !term && (i === 0 || groupFor(list[i - 1]) !== group);
          return (
            <Fragment key={s.id}>
              {showGroup && <p className="px-3 pt-3 pb-1 text-[11px] font-semibold tracking-wide text-muted uppercase">{group}</p>}
              {editing?.id === s.id ? (
                <form onSubmit={(e) => { e.preventDefault(); void saveRename(); }} className="mb-0.5 flex items-center gap-1.5 rounded-lg bg-surface-2 px-2 py-1.5">
                  <input autoFocus value={editing.value} maxLength={200} aria-label="Conversation name"
                    onFocus={(e) => e.target.select()}
                    onChange={(e) => setEditing({ id: s.id, value: e.target.value })}
                    onKeyDown={(e) => { if (e.key === "Escape") { e.preventDefault(); setEditing(null); } }}
                    onBlur={(e) => {
                      // Clicking Save/Cancel moves focus to that button: let its own handler decide.
                      if (!e.currentTarget.form?.contains(e.relatedTarget as Node | null)) void saveRename();
                    }}
                    className="h-8 min-w-0 flex-1 rounded-md border border-brand-400 bg-surface px-2 text-sm text-ink focus:ring-2 focus:ring-brand-500/20 focus:outline-none" />
                  <button type="submit" disabled={saving} aria-label="Save name" title="Save (Enter)"
                    className="grid size-7 shrink-0 place-items-center rounded-md text-success hover:bg-success-soft disabled:opacity-60">
                    {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-4" />}
                  </button>
                  <button type="button" onClick={() => setEditing(null)} disabled={saving} aria-label="Cancel renaming" title="Cancel (Esc)"
                    className="grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink">
                    <X className="size-4" />
                  </button>
                </form>
              ) : confirming === s.id ? (
                <div role="group" aria-label={`Delete ${s.title}?`}
                  className="mb-0.5 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2">
                  <span className="min-w-0 flex-1 truncate text-sm text-danger">Delete this conversation?</span>
                  <button onClick={() => remove(s.id)} disabled={deleting} autoFocus
                    onKeyDown={(e) => e.key === "Escape" && setConfirming(null)}
                    className="flex h-7 items-center gap-1 rounded-md bg-danger px-2.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-60">
                    {deleting && <Loader2 className="size-3 animate-spin" />} Delete
                  </button>
                  <button onClick={() => setConfirming(null)} disabled={deleting}
                    className="h-7 rounded-md px-2 text-xs font-medium text-muted hover:bg-surface hover:text-ink">
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="group relative mb-0.5">
                  <button
                    onClick={() => onSelect(s.id)}
                    disabled={disabled}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "relative flex w-full items-start gap-2.5 rounded-lg py-2.5 pr-24 pl-3 text-left transition-colors disabled:opacity-60",
                      active ? "bg-brand-50 dark:bg-brand-900/30" : "hover:bg-surface-2",
                    )}
                  >
                    {active && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-brand-600" aria-hidden />}
                    <span className="min-w-0 flex-1">
                      <span className={cn("flex items-center gap-1.5 text-sm", active ? "font-medium text-brand-700 dark:text-brand-200" : "text-ink")}>
                        {s.pinned && <Pin className="size-3 shrink-0 fill-current text-brand-500" aria-label="Pinned" />}
                        <span className="min-w-0 truncate">{highlight(s.title, term)}</span>
                      </span>
                      <span className="block text-[11px] text-muted">{timeAgo(s.lastMessageAt)}</span>
                      {term && s.snippet && <span className="mt-0.5 line-clamp-2 block text-xs leading-snug text-muted">{highlight(s.snippet, term)}</span>}
                    </span>
                  </button>
                  {/* Shown on hover or keyboard focus; always visible on touch screens (no hover there). */}
                  <div className={cn("absolute top-2 right-2 flex gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 [@media(hover:none)]:opacity-100",
                    disabled && "hidden")}>
                    <button onClick={() => void onPin(s.id, !s.pinned)} aria-pressed={s.pinned}
                      aria-label={`${s.pinned ? "Unpin" : "Pin"} conversation: ${s.title}`} title={s.pinned ? "Unpin" : "Pin to top"}
                      className={cn("grid size-7 place-items-center rounded-md hover:bg-surface hover:text-ink",
                        s.pinned ? "text-brand-600 dark:text-brand-300" : "text-muted")}>
                      {s.pinned ? <PinOff className="size-3.5" /> : <Pin className="size-3.5" />}
                    </button>
                    <button onClick={() => { setConfirming(null); setEditing({ id: s.id, value: s.title }); }}
                      aria-label={`Rename conversation: ${s.title}`} title="Rename"
                      className="grid size-7 place-items-center rounded-md text-muted hover:bg-surface hover:text-ink">
                      <Pencil className="size-3.5" />
                    </button>
                    <button onClick={() => { setEditing(null); setConfirming(s.id); }} aria-label={`Delete conversation: ${s.title}`}
                      title="Delete"
                      className="grid size-7 place-items-center rounded-md text-muted hover:bg-danger-soft hover:text-danger">
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                </div>
              )}
            </Fragment>
          );
        })}
      </nav>

      <div className="m-3 flex gap-2 rounded-xl bg-surface-2 p-3 text-xs text-muted">
        <ShieldCheck className="size-4 shrink-0 text-success" />
        <p>The copilot can only <b className="text-ink">request</b> actions. You approve every one.</p>
      </div>
    </div>
  );
}
