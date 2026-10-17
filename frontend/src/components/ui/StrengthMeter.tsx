import { cn } from "../../lib/cn";

/** Rough guide only; the server enforces the real rule (10+ characters). */
function strength(pw: string): { score: number; label: string } {
  if (!pw) return { score: 0, label: "At least 10 characters. A short sentence works well." };
  let score = pw.length >= 10 ? 1 : 0;
  if (pw.length >= 14) score++;
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++;
  if (/\d/.test(pw) || /[^A-Za-z0-9]/.test(pw) || / /.test(pw)) score++;
  if (pw.length < 10) return { score: 0, label: `${10 - pw.length} more character${pw.length === 9 ? "" : "s"} needed` };
  return { score, label: ["Too short", "Okay", "Good", "Strong", "Very strong"][score] };
}

export function StrengthMeter({ password }: { password: string }) {
  const { score, label } = strength(password);
  const colour = score <= 1 ? "bg-danger" : score === 2 ? "bg-warning" : "bg-success";
  return (
    <div className="mt-2">
      <div className="flex gap-1" aria-hidden>
        {[1, 2, 3, 4].map((i) => (
          <span key={i} className={cn("h-1 flex-1 rounded-full transition-colors", password && i <= Math.max(score, 1) ? colour : "bg-surface-2")} />
        ))}
      </div>
      <p className="mt-1 text-xs text-muted" aria-live="polite">{label}</p>
    </div>
  );
}
