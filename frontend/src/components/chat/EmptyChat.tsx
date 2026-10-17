import { ArrowUpRight, CalendarClock, Eye, FlaskConical, Gauge, Landmark, LineChart, ReceiptText, ShieldCheck, Sparkles, type LucideIcon } from "lucide-react";

// Prompts work for any business (no demo customer names or fixed currency amounts).
const SUGGESTIONS: { icon: LucideIcon; title: string; prompt: string; tone: string }[] = [
  { icon: LineChart, title: "Cash runway", prompt: "Will I run out of cash in the next 3 months?",
    tone: "bg-info-soft text-info" },
  { icon: Gauge, title: "Business health", prompt: "How healthy is my business, and what's the weakest area?",
    tone: "bg-success-soft text-success" },
  { icon: ReceiptText, title: "Collect payments", prompt: "Who owes me money? Remind the most overdue customer.",
    tone: "bg-danger-soft text-danger" },
  { icon: CalendarClock, title: "Upcoming bills", prompt: "Which bills are due soon, and can I pay them all on time?",
    tone: "bg-warning-soft text-warning" },
  { icon: Landmark, title: "Financing", prompt: "What financing would cover the upcoming cash gap?",
    tone: "bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-200" },
  { icon: FlaskConical, title: "What-if", prompt: "What if my biggest customer pays 30 days late?",
    tone: "bg-info-soft text-info" },
];

const CAPABILITIES: { icon: LucideIcon; label: string }[] = [
  { icon: Eye, label: "Reads your ledger" },
  { icon: Sparkles, label: "Analyses & forecasts" },
  { icon: ShieldCheck, label: "Acts only with approval" },
];

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

export function EmptyChat({ name, onPick }: { name?: string; onPick: (prompt: string) => void }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center py-10 text-center">
      <div className="relative">
        <div className="absolute -inset-2 rounded-[1.75rem] bg-brand-500/25 blur-2xl" aria-hidden />
        <span className="relative grid size-16 place-items-center rounded-3xl bg-gradient-to-br from-brand-400 via-brand-600 to-brand-800 text-white shadow-xl ring-4 ring-surface">
          <Sparkles className="size-8" />
        </span>
      </div>
      <h2 className="mt-6 text-2xl font-semibold tracking-tight text-ink sm:text-3xl">
        {greeting()}{name ? `, ${name}` : ""}
      </h2>
      <p className="mt-2 max-w-lg text-sm leading-relaxed text-muted sm:text-base">
        Ask me about your cash, customers, bills or financing. Every figure comes straight from your ledger.
      </p>
      <ul className="mt-5 flex flex-wrap justify-center gap-2">
        {CAPABILITIES.map(({ icon: Icon, label }) => (
          <li key={label} className="flex items-center gap-1.5 rounded-full border border-line bg-surface/80 px-3 py-1 text-xs text-muted backdrop-blur">
            <Icon className="size-3.5 text-brand-600 dark:text-brand-300" /> {label}
          </li>
        ))}
      </ul>

      <p className="mt-10 mb-3 w-full text-left text-xs font-semibold tracking-wide text-muted uppercase">Try asking</p>
      <div className="grid w-full gap-3 text-left sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, title, prompt, tone }) => (
          <button
            key={title}
            onClick={() => onPick(prompt)}
            className="group relative flex items-start gap-3 rounded-2xl border border-line bg-surface p-4 text-left shadow-card transition-all hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-md motion-reduce:hover:translate-y-0 dark:hover:border-brand-700"
          >
            <span className={`grid size-9 shrink-0 place-items-center rounded-xl ${tone}`}>
              <Icon className="size-4.5" />
            </span>
            <span className="min-w-0 pr-5">
              <span className="block text-sm font-semibold text-ink">{title}</span>
              <span className="mt-0.5 block text-sm leading-snug text-muted group-hover:text-ink/80">{prompt}</span>
            </span>
            <ArrowUpRight className="absolute top-4 right-4 size-4 text-muted opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
          </button>
        ))}
      </div>
    </div>
  );
}
