import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { api } from "../../lib/api";
import { cn } from "../../lib/cn";
import { APPROVALS_CHANGED } from "../../lib/events";
import { NAV_ITEMS } from "./nav";

/** Count of approval requests waiting for a decision (refreshed on navigation, on change events and every 30 s). */
function usePendingApprovals(): number {
  const [count, setCount] = useState(0);
  const { pathname } = useLocation();
  useEffect(() => {
    let alive = true;
    const load = () => api<unknown[]>("/approvals?status=pending").then((r) => alive && setCount(r.length)).catch(() => {});
    load();
    const t = setInterval(load, 30_000);
    window.addEventListener(APPROVALS_CHANGED, load);
    return () => { alive = false; clearInterval(t); window.removeEventListener(APPROVALS_CHANGED, load); };
  }, [pathname]);
  return count;
}

const COLLAPSED_KEY = "sidebar-collapsed";

/** Desktop sidebar state, remembered per browser (a viewer convenience, so localStorage is fine). */
function useCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSED_KEY) === "1"; } catch { return false; }
  });
  const toggle = useCallback(() => setCollapsed((c) => {
    try { localStorage.setItem(COLLAPSED_KEY, c ? "0" : "1"); } catch { /* storage unavailable: still toggles */ }
    return !c;
  }), []);
  useEffect(() => {
    // Ctrl/Cmd + B, as in most editors.
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b" && !e.altKey && !e.shiftKey) {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);
  return [collapsed, toggle];
}

/** Hover / focus label for icon-only items. */
function Tip({ show, children }: { show: boolean; children: string }) {
  if (!show) return null;
  return (
    <span aria-hidden className="pointer-events-none absolute left-full z-50 ml-3 rounded-md bg-ink px-2 py-1 text-xs font-medium whitespace-nowrap text-surface opacity-0 shadow-lg transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
      {children}
    </span>
  );
}

export function Logo({ compact = false, iconOnly = false }: { compact?: boolean; iconOnly?: boolean }) {
  return (
    <div className="flex shrink-0 items-center gap-2.5">
      <img src="/favicon.svg" alt="SME Finance Copilot" className="size-8" />
      <div className={cn("leading-tight whitespace-nowrap", compact && "hidden sm:block", iconOnly && "sr-only")}>
        <p className="text-sm font-semibold text-ink">SME Finance</p>
        <p className="text-xs text-muted">Copilot</p>
      </div>
    </div>
  );
}

export function SidebarNav({ onNavigate, collapsed = false }: { onNavigate?: () => void; collapsed?: boolean }) {
  const pending = usePendingApprovals();
  return (
    <nav className="flex flex-col gap-1" aria-label="Main">
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "group relative flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition-colors",
              collapsed ? "justify-center px-0" : "px-3",
              isActive
                ? "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200"
                : "text-muted hover:bg-surface-2 hover:text-ink",
            )
          }
        >
          <Icon className="size-4.5 shrink-0" aria-hidden />
          <span className={cn(collapsed && "sr-only")}>{label}</span>
          {to === "/approvals" && pending > 0 && (collapsed ? (
            <span className="absolute top-1.5 right-3.5 size-2 rounded-full bg-warning ring-2 ring-surface" aria-label={`${pending} pending`} />
          ) : (
            <span className="ml-auto rounded-full bg-warning px-1.5 py-0.5 text-[10px] leading-none font-semibold text-white"
              aria-label={`${pending} pending`}>{pending}</span>
          ))}
          <Tip show={collapsed}>{to === "/approvals" && pending > 0 ? `${label} (${pending})` : label}</Tip>
        </NavLink>
      ))}
    </nav>
  );
}

export function Sidebar() {
  const [collapsed, toggle] = useCollapsed();
  const ToggleIcon = collapsed ? PanelLeftOpen : PanelLeftClose;
  return (
    // Pinned to the viewport: the page scrolls, the sidebar stays put. Only the menu scrolls if it overflows.
    // z-30: `sticky` makes the aside its own stacking layer, so without a z-index the page content painted
    // after it (cards with `relative`) would cover the rail's tooltips. Above the topbar (z-20) too.
    <aside className={cn("sticky top-0 z-30 hidden h-dvh shrink-0 flex-col border-r border-line bg-surface py-5 transition-[width] duration-200 lg:flex",
      collapsed ? "w-[72px] px-3" : "w-60 px-4")}>
      <div className={cn("flex", collapsed && "justify-center")}><Logo iconOnly={collapsed} /></div>
      {/* Tooltips stick out to the right, so the icon rail must not clip them. */}
      <div className={cn("mt-8 -mx-1 min-h-0 flex-1 px-1", collapsed ? "overflow-visible" : "overflow-y-auto")}>
        <SidebarNav collapsed={collapsed} />
      </div>
      {!collapsed && (
        <div className="mt-4 shrink-0 rounded-xl bg-surface-2 p-3 text-xs text-muted">
          The copilot never moves money or contacts anyone on its own. Approved actions are recorded for you to complete.
        </div>
      )}
      <button onClick={toggle} aria-expanded={!collapsed} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        title={`${collapsed ? "Expand" : "Collapse"} sidebar (Ctrl+B)`}
        className={cn("group relative mt-3 flex shrink-0 items-center gap-3 rounded-lg py-2 text-sm font-medium text-muted transition-colors hover:bg-surface-2 hover:text-ink",
          collapsed ? "justify-center px-0" : "px-3")}>
        <ToggleIcon className="size-4.5 shrink-0" aria-hidden />
        {!collapsed && <span>Collapse</span>}
      </button>
    </aside>
  );
}
