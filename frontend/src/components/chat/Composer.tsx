import { ArrowUp, Square } from "lucide-react";
import { forwardRef, type KeyboardEvent } from "react";
import { cn } from "../../lib/cn";

const MAX = 2000;

interface Props {
  value: string;
  busy: boolean;
  readOnly?: boolean;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
}

/** Chat input: auto-growing textarea, Enter to send, Shift+Enter for a new line, Stop while streaming. */
export const Composer = forwardRef<HTMLTextAreaElement, Props>(function Composer(
  { value, busy, readOnly, onChange, onSend, onStop }, ref,
) {
  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!busy) onSend();
    }
  }

  const near = value.length > MAX * 0.8;

  return (
    <div className="rounded-2xl border border-line bg-surface shadow-lg shadow-black/5 transition focus-within:border-brand-400 focus-within:ring-4 focus-within:ring-brand-500/10 dark:shadow-black/30">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        maxLength={MAX}
        onChange={(e) => {
          onChange(e.target.value);
          e.target.style.height = "auto";
          e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
        }}
        onKeyDown={onKeyDown}
        placeholder="Ask about cash flow, invoices, financing…"
        aria-label="Message the copilot"
        className="block max-h-[200px] min-h-14 w-full resize-none bg-transparent px-4 pt-4 pb-1 text-[15px] leading-relaxed text-ink placeholder:text-muted focus:outline-none"
      />
      <div className="flex items-center gap-3 px-3 pt-1 pb-3">
        <p className="hidden flex-1 truncate pl-1 text-xs text-muted sm:block">
          <kbd className="rounded border border-line bg-surface-2 px-1 font-sans text-[11px]">Enter</kbd> to send ·{" "}
          <kbd className="rounded border border-line bg-surface-2 px-1 font-sans text-[11px]">Shift + Enter</kbd> new line
          {readOnly && " · read-only access"}
        </p>
        <span className="flex-1 sm:hidden" />
        {near && <span className={cn("num text-xs", value.length >= MAX ? "text-danger" : "text-muted")}>{value.length}/{MAX}</span>}
        {busy ? (
          <button
            onClick={onStop}
            className="flex h-9 items-center gap-1.5 rounded-xl border border-line bg-surface px-3 text-sm font-medium text-ink transition-colors hover:bg-surface-2"
          >
            <Square className="size-3.5 fill-current" /> Stop
          </button>
        ) : (
          <button
            onClick={onSend}
            disabled={!value.trim()}
            aria-label="Send message"
            className="grid size-9 place-items-center rounded-xl bg-brand-600 text-white shadow-sm transition-colors hover:bg-brand-700 disabled:bg-surface-2 disabled:text-muted disabled:shadow-none"
          >
            <ArrowUp className="size-4.5" strokeWidth={2.5} />
          </button>
        )}
      </div>
    </div>
  );
});
