import { ArrowLeft, BellRing, HandCoins, Moon, ShieldCheck, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useTheme } from "../../lib/theme";

/** Illustrations live in public/assets (served as-is). */
export const ILLUSTRATIONS = {
  signIn: { src: "/assets/financeanalysis.svg" },
  register: { src: "/assets/financeanalysis2.svg" },
} as const;

type Illustration = (typeof ILLUSTRATIONS)[keyof typeof ILLUSTRATIONS];

/**
 * Signed-out pages (sign in, register, password reset, invitations): the brand panel on the left half
 * (large screens only), and the form in a card on the right. Every page uses the same card width.
 */
export function AuthLayout({ title, subtitle, children, footer, back, illustration = ILLUSTRATIONS.signIn }: {
  title: string;
  subtitle?: ReactNode;
  children: ReactNode;
  /** Below the form, inside the card (e.g. "New here? Create an account"). */
  footer?: ReactNode;
  /** Link above the card, e.g. back to sign in. */
  back?: { to: string; label: string };
  illustration?: Illustration;
}) {
  const { theme, toggle } = useTheme();
  return (
    <div className="flex min-h-dvh bg-canvas">
      <BrandPanel illustration={illustration} />

      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        {/* Faint dot grid and a soft glow give the empty space some depth. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(var(--color-line)_1px,transparent_1px)] [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)] [background-size:22px_22px]" />
        <div aria-hidden className="pointer-events-none absolute top-1/2 left-1/2 size-[36rem] -translate-1/2 rounded-full bg-brand-500/10 blur-3xl dark:bg-brand-500/15" />

        <div className="relative flex items-center justify-between px-5 pt-5 sm:px-8">
          <Link to="/" className="flex items-center gap-2.5 lg:invisible" tabIndex={-1}>
            <img src="/favicon.svg" alt="" className="size-8" />
            <span className="text-sm font-semibold text-ink">SME Finance Copilot</span>
          </Link>
          <button onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            className="grid size-9 place-items-center rounded-lg border border-line bg-surface/70 text-muted backdrop-blur hover:bg-surface hover:text-ink">
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>
        </div>

        <div className="relative flex flex-1 flex-col items-center justify-center px-4 py-8 sm:px-8">
          <div className="w-full max-w-[30rem]">
            {back && (
              <Link to={back.to} className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-muted transition-colors hover:text-ink">
                <ArrowLeft className="size-4" /> {back.label}
              </Link>
            )}
            <div className="rounded-2xl border border-line bg-surface p-6 shadow-xl shadow-slate-900/5 sm:p-9 dark:shadow-black/30">
              <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
              {subtitle && <p className="mt-1.5 text-sm leading-relaxed text-muted">{subtitle}</p>}
              <div className="mt-7">{children}</div>
              {footer && <div className="mt-7 border-t border-line pt-5 text-center text-sm text-muted">{footer}</div>}
            </div>
          </div>
        </div>

        <p className="relative px-5 pb-5 text-center text-xs text-muted">
          © {new Date().getFullYear()} SME Finance Copilot · Encrypted sessions · You approve every action
        </p>
      </main>
    </div>
  );
}

/** Shared link style for the auth pages. */
export const authLink = "font-medium text-brand-600 hover:text-brand-700 hover:underline dark:text-brand-300";

const FEATURES = [
  { icon: BellRing, title: "Cash-flow alerts", text: "Know about a shortfall weeks ahead" },
  { icon: HandCoins, title: "Financing matches", text: "Ranked options that fit your numbers" },
  { icon: ShieldCheck, title: "You stay in control", text: "Nothing happens without your approval" },
];

/**
 * Left side: the illustration fills the panel on plain white (the artwork's own background), with the
 * headline above it. Fixed light colours: it looks the same in light and dark mode.
 */
function BrandPanel({ illustration }: { illustration: Illustration }) {
  return (
    <aside className="sticky top-0 hidden h-dvh w-1/2 shrink-0 flex-col border-r border-slate-200 bg-white lg:flex">
      <div className="px-10 pt-10 xl:px-14">
        <Link to="/" className="inline-flex items-center gap-3">
          <img src="/favicon.svg" alt="" className="size-9" />
          <span className="text-base font-semibold tracking-tight text-slate-900">SME Finance Copilot</span>
        </Link>
        <h2 className="mt-10 max-w-lg text-3xl leading-tight font-semibold tracking-tight text-slate-900 xl:text-4xl [@media(max-height:700px)]:mt-6 [@media(max-height:700px)]:text-2xl">
          Your finance team, <span className="text-brand-600">in one copilot.</span>
        </h2>
        <p className="mt-3 max-w-md text-sm leading-relaxed text-slate-600">
          Import your bank statements and get clear analysis, cash-flow alerts and financing options. You decide every action.
        </p>
      </div>

      {/* The artwork takes all remaining height, never cropped. */}
      <div className="flex min-h-0 flex-1 items-center justify-center px-6 py-4 xl:px-10">
        <img src={illustration.src} alt="" aria-hidden decoding="async" className="size-full max-h-full object-contain" />
      </div>

      <ul className="grid grid-cols-3 gap-3 px-10 pb-10 xl:px-14 [@media(max-height:760px)]:hidden">
        {FEATURES.map(({ icon: Icon, title, text }) => (
          <li key={title} className="rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
            <span className="grid size-8 place-items-center rounded-lg bg-brand-50 text-brand-600"><Icon className="size-4" /></span>
            <p className="mt-2.5 text-sm font-semibold text-slate-900">{title}</p>
            <p className="mt-0.5 text-xs leading-snug text-slate-500">{text}</p>
          </li>
        ))}
      </ul>
    </aside>
  );
}
