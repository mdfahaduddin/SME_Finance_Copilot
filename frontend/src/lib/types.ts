export type Role = "owner" | "accountant" | "viewer";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  mfaEnabled: boolean;
  business?: { id: number; name: string; onboardingStatus: "accounts" | "data" | "complete"; currency: string };
}

export interface Health {
  status: string;
  llmMode: "online" | "offline";
}

export type Severity = "critical" | "high" | "medium" | "low";

export interface Alert {
  id: number;
  type: string;
  severity: Severity;
  title: string;
  detail: string;
  suggestedAction: string;
  status: "open" | "acknowledged" | "resolved";
  createdAt: string;
}

export interface HealthComponent {
  key: string;
  label: string;
  score: number;
  weight: number;
  contribution: number;
  value: string;
  explanation: string;
}

export interface ForecastWeek {
  week: number;
  start: string;
  closing: number;
  p10: number;
  p90: number;
  inflows: number;
  outflows: number;
}

export interface ForecastSummary {
  openingBalance: number;
  endingBalance: number;
  lowestBalance: number;
  lowestWeek: number;
  lowestWeekStart: string;
  lowestP10: number;
  safetyBuffer: number;
  firstNegativeWeek: number | null;
  firstBelowBufferWeek: number | null;
  shortfallAmount: number;
  atRiskReceivables: number;
}

export interface DashboardSummary {
  asOf: string;
  business: { name: string; industry: string; yearsInBusiness: number; employees: number; currency: string };
  accounts: { name: string; type: string; number: string; balance: number }[];
  healthScore: { score: number | null; grade: string; weakestArea: string | null; components: HealthComponent[]; message?: string };
  kpis: {
    operatingCash: number;
    totalCash: number;
    cashCoverMonths: number | null;
    revenue12m: number;
    revenueGrowthYoY: number | null;
    netMargin: number;
    dso: number;
    overdueReceivables: number;
  };
  forecast: { summary: ForecastSummary; weeks: ForecastWeek[] };
  monthly: { month: string; partial: boolean; revenue: number; inflows: number; outflows: number; netCashFlow: number }[];
  alerts: Alert[];
  openAlertCount: number;
  pendingApprovals: number;
}

// ---- Copilot chat ----

export type Tier = "T0" | "T1" | "T2" | "?";

export interface ToolTraceEntry {
  id: string;
  name: string;
  tier: Tier;
  args: Record<string, unknown>;
  decision: "allowed" | "denied" | "refused" | "error" | "pending_approval";
  summary: string;
  ms: number;
  approvalRequestId?: number;
}

export interface Groundedness {
  checked: number;
  grounded: number;
  unverified: string[];
}

export interface ChatMessage {
  id: number | string;
  role: "user" | "assistant";
  content: string;
  toolTrace: ToolTraceEntry[];
  mode?: "online" | "offline";
  groundedness?: Groundedness;
  approvalRequests?: number[];
  piiMasked?: number;
  pending?: boolean; // still streaming
  liveTools?: { id: string; name: string; tier: Tier; done: boolean }[];
  status?: string;
  error?: string;
  createdAt?: string;
}

export interface ChatSession {
  id: number;
  title: string;
  createdAt: string;
  lastMessageAt: string;
  /** Pinned conversations are listed first. */
  pinned: boolean;
  /** Only in search results: an excerpt of the first matching message ("" when only the title matched). */
  snippet?: string;
}

export type ChatEvent =
  | { type: "status"; text: string }
  | { type: "reset" }
  | { type: "delta"; text: string }
  | { type: "tool_call"; id: string; name: string; tier: Tier }
  | ({ type: "tool_result" } & ToolTraceEntry)
  | { type: "approval"; requestId: number; summary: string }
  | ({ type: "final"; messageId: number; content: string; toolTrace: ToolTraceEntry[] } & Required<
      Pick<ChatMessage, "mode" | "groundedness" | "approvalRequests" | "piiMasked">
    >)
  | { type: "error"; message: string };

export interface ApprovalRequest {
  id: number;
  tool: string;
  summary: string;
  requestedVia: "ui" | "agent";
  params: Record<string, unknown>;
  rationale: string;
  riskLevel: "low" | "medium" | "high";
  amount: number | null;
  status: "pending" | "approved" | "rejected" | "executed" | "expired" | "failed";
  decisionReason: string;
  result: { message: string; referenceNo?: string } | null;
  requiresReauth: boolean;
  approverRoles: Role[];
  createdAt: string;
  decidedAt: string | null;
  expiresAt: string;
}
