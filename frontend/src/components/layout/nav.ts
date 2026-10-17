import {
  Bot, Database, FileBarChart, Gauge, HandCoins, LineChart, ScrollText, Settings, ShieldCheck, Users, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/copilot", label: "Copilot", icon: Bot },
  { to: "/cash-flow", label: "Cash Flow", icon: LineChart },
  { to: "/financing", label: "Financing", icon: HandCoins },
  { to: "/approvals", label: "Approvals", icon: ShieldCheck },
  { to: "/reports", label: "Reports", icon: FileBarChart },
  { to: "/data", label: "Data", icon: Database },
  { to: "/team", label: "Team", icon: Users },
  { to: "/audit", label: "Audit Log", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: Settings },
];
