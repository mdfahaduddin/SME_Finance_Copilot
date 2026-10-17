import { LogOut, Menu, Moon, Sun, X } from "lucide-react";
import { useState } from "react";
import { useAuth } from "../../lib/auth";
import { useTheme } from "../../lib/theme";
import type { Health } from "../../lib/types";
import { useApi } from "../../lib/useApi";
import { Badge } from "../ui/Badge";
import { Logo, SidebarNav } from "./Sidebar";

export function Topbar() {
  const { theme, toggle } = useTheme();
  const { user, logout } = useAuth();
  const initials = (user?.name ?? "?").split(" ").map((p) => p[0]).join("").slice(0, 2);
  const [open, setOpen] = useState(false);
  const { data: health, error } = useApi<Health>("/health");

  return (
    <>
      <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-line bg-surface/85 px-4 backdrop-blur sm:px-6">
        <button
          className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2 lg:hidden"
          onClick={() => setOpen(true)}
          aria-label="Open menu"
        >
          <Menu className="size-5" />
        </button>
        <div className="lg:hidden">
          <Logo compact />
        </div>

        <div className="ml-auto flex items-center gap-2">
          {error ? (
            <Badge tone="danger">API offline</Badge>
          ) : health ? (
            <Badge tone={health.llmMode === "online" ? "success" : "warning"}>
              <span className="size-1.5 rounded-full bg-current" />
              AI {health.llmMode === "online" ? "online" : "offline mode"}
            </Badge>
          ) : null}
          <button
            className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
            onClick={toggle}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
          >
            {theme === "dark" ? <Sun className="size-4.5" /> : <Moon className="size-4.5" />}
          </button>
          <div className="flex items-center gap-2 border-l border-line pl-3">
            <span className="grid size-8 place-items-center rounded-full bg-brand-600 text-xs font-semibold text-white">
              {initials}
            </span>
            <div className="hidden leading-tight sm:block">
              <p className="text-xs font-medium text-ink">{user?.name}</p>
              <p className="text-xs text-muted capitalize">{user?.role}</p>
            </div>
            <button
              className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink"
              onClick={() => void logout()}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="size-4.5" />
            </button>
          </div>
        </div>
      </header>

      {/* Mobile drawer */}
      {open && (
        <div className="fixed inset-0 z-30 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col bg-surface px-4 py-5 shadow-xl">
            <div className="flex items-center justify-between">
              <Logo />
              <button
                className="grid size-9 place-items-center rounded-lg text-muted hover:bg-surface-2"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
              >
                <X className="size-5" />
              </button>
            </div>
            <div className="mt-8 min-h-0 flex-1 overflow-y-auto">
              <SidebarNav onNavigate={() => setOpen(false)} />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
