import { AlertOctagon, AlertTriangle, Info, ShieldAlert } from "lucide-react";
import { cn } from "../../lib/cn";
import type { Alert, Severity } from "../../lib/types";
import { Badge, type Tone } from "./Badge";

const STYLE: Record<Severity, { tone: Tone; icon: typeof Info; color: string }> = {
  critical: { tone: "danger", icon: AlertOctagon, color: "text-danger" },
  high: { tone: "danger", icon: ShieldAlert, color: "text-danger" },
  medium: { tone: "warning", icon: AlertTriangle, color: "text-warning" },
  low: { tone: "info", icon: Info, color: "text-info" },
};

export function AlertItem({ alert, compact = false }: { alert: Alert; compact?: boolean }) {
  const { tone, icon: Icon, color } = STYLE[alert.severity];
  return (
    <div className="flex gap-3 py-3">
      <Icon className={cn("mt-0.5 size-4.5 shrink-0", color)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-ink">{alert.title}</p>
          <Badge tone={tone}>{alert.severity}</Badge>
        </div>
        {!compact && <p className="mt-1 text-sm text-muted">{alert.detail}</p>}
        <p className="mt-1 text-xs text-brand-700 dark:text-brand-300">→ {alert.suggestedAction}</p>
      </div>
    </div>
  );
}
