import { Outlet, useMatch } from "react-router-dom";
import { cn } from "../../lib/cn";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

export function AppShell() {
  // The copilot is a full-height chat workspace; every other page is a padded, centred document.
  const fullBleed = useMatch("/copilot") !== null;
  return (
    <div className="flex min-h-dvh">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        {/* Wide cap (1680px): fills large monitors; only ultra-wide screens get side margins. */}
        <main className={cn("flex-1", fullBleed ? "min-h-0" : "mx-auto w-full max-w-[1680px] px-4 py-6 sm:px-6 lg:py-8 xl:px-8")}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
