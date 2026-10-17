import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "./cn";

/**
 * Lightweight toasts: call `toast.success("Saved")` from anywhere (no provider or hook needed) and the
 * single <Toaster /> mounted in main.tsx shows it. Use them to confirm an action; keep form validation
 * errors next to the form, where the user can fix them.
 */
type Kind = "success" | "error" | "info";
interface Toast { id: number; kind: Kind; title: string; description?: string }

const MAX_VISIBLE = 4;
const DURATION: Record<Kind, number> = { success: 4000, info: 4000, error: 7000 };

let toasts: Toast[] = [];
let nextId = 1;
const listeners = new Set<(t: Toast[]) => void>();
const timers = new Map<number, ReturnType<typeof setTimeout>>();

function emit() {
  for (const l of listeners) l(toasts);
}

function dismiss(id: number) {
  clearTimeout(timers.get(id));
  timers.delete(id);
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

function schedule(id: number, ms: number) {
  clearTimeout(timers.get(id));
  timers.set(id, setTimeout(() => dismiss(id), ms));
}

function show(kind: Kind, title: string, description?: string) {
  const id = nextId++;
  toasts = [...toasts, { id, kind, title, description }].slice(-MAX_VISIBLE);
  emit();
  schedule(id, DURATION[kind]);
  return id;
}

export const toast = {
  success: (title: string, description?: string) => show("success", title, description),
  error: (title: string, description?: string) => show("error", title, description),
  info: (title: string, description?: string) => show("info", title, description),
  dismiss,
};

/** Message of a caught error, for `toast.error("Could not save", errorText(e))`. */
export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

const STYLE: Record<Kind, { icon: typeof Info; tone: string }> = {
  success: { icon: CheckCircle2, tone: "text-success" },
  error: { icon: XCircle, tone: "text-danger" },
  info: { icon: Info, tone: "text-brand-600 dark:text-brand-300" },
};

export function Toaster() {
  const [items, setItems] = useState<Toast[]>(toasts);
  useEffect(() => {
    listeners.add(setItems);
    return () => { listeners.delete(setItems); };
  }, []);

  return (
    // Bottom-right on desktop, full width at the bottom on phones. Above every overlay (z-30 drawers).
    <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6">
      {items.map((t) => {
        const { icon: Icon, tone } = STYLE[t.kind];
        return (
          <div key={t.id} role={t.kind === "error" ? "alert" : "status"}
            // Pause while the pointer is over it, so a long message can be read.
            onMouseEnter={() => clearTimeout(timers.get(t.id))}
            onMouseLeave={() => schedule(t.id, 2000)}
            className="toast-in pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-lg ring-1 ring-black/5 dark:ring-white/5">
            <Icon className={cn("mt-0.5 size-5 shrink-0", tone)} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">{t.title}</p>
              {t.description && <p className="mt-0.5 text-xs break-words text-muted">{t.description}</p>}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss notification"
              className="-m-1 grid size-7 shrink-0 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink">
              <X className="size-4" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
