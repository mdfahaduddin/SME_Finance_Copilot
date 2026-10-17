import { Check, Cpu, EyeOff, KeyRound, Minus, ShieldCheck, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "../components/ui/Badge";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { TierBadge, TOOL_LABELS } from "../components/chat/ToolTrace";
import { BusinessProfileCard } from "../components/settings/BusinessProfileCard";
import { SecuritySettings } from "../components/settings/SecuritySettings";
import { useAuth } from "../lib/auth";
import { money } from "../lib/format";
import type { Role, Tier } from "../lib/types";
import { useApi } from "../lib/useApi";

interface Policy {
  reauthThreshold: number;
  schedulePaymentMax: number;
  schedulePaymentDailyMax: number;
  requestTtlHours: number;
  safetyBufferWeeks: number;
  sessionMinutes: number;
  agent: { maxStepsPerTurn: number; maxActionsPerTurn: number; mode: "online" | "offline"; model: string | null };
  roleTiers: Record<Role, Tier[]>;
  approverRoles: Record<string, Role[]>;
  tools: { name: string; tier: Tier }[];
}

const ROLES: Role[] = ["owner", "accountant", "viewer"];
const ACTION_LABELS: Record<string, string> = {
  send_payment_reminder: "Approve payment reminders",
  schedule_payment: "Approve supplier payments",
  request_bill_deferral: "Approve bill deferral requests",
  submit_loan_application: "Approve financing applications",
};

function Yes({ on }: { on: boolean }) {
  return on
    ? <Check className="mx-auto size-4 text-success" aria-label="Allowed" />
    : <Minus className="mx-auto size-4 text-muted/60" aria-label="Not allowed" />;
}

function Item({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="text-right text-sm font-medium text-ink">{value}</dd>
    </div>
  );
}

export default function Settings() {
  const { user } = useAuth();
  const { data: p } = useApi<Policy>("/policy");

  return (
    <>
      <PageHeader title="Settings" description="Your account, the AI configuration and the safety rules the server enforces." />

      <div className="grid gap-4 lg:grid-cols-2">
        <BusinessProfileCard />
        <SecuritySettings />
        <Card>
          <CardHeader title="Account" />
          <CardBody>
            <div className="flex items-center gap-3">
              <span className="grid size-11 place-items-center rounded-full bg-brand-600 text-white"><UserRound className="size-5" /></span>
              <div>
                <p className="text-sm font-semibold text-ink">{user?.name}</p>
                <p className="text-xs text-muted">{user?.email}</p>
              </div>
              <Badge tone="brand" className="ml-auto capitalize">{user?.role}</Badge>
            </div>
            <dl className="mt-4 divide-y divide-line">
              <Item label="Signed out after inactivity" value={p ? `${p.sessionMinutes} minutes` : "…"} />
              <Item label="Session" value="Secure HttpOnly cookie" />
            </dl>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="AI copilot" subtitle="How the agent runs and what it may do" />
          <CardBody>
            {!p ? <Skeleton className="h-40" /> : (
              <dl className="divide-y divide-line">
                <Item label="Mode" value={p.agent.mode === "online"
                  ? <Badge tone="success"><Cpu className="size-3" />Online · {p.agent.model}</Badge>
                  : <Badge tone="warning">Offline rule-based mode</Badge>} />
                <Item label="Steps per answer" value={`up to ${p.agent.maxStepsPerTurn}`} />
                <Item label="Action requests per answer" value={`up to ${p.agent.maxActionsPerTurn}`} />
                <Item label="Personal data" value={<span className="flex items-center gap-1"><EyeOff className="size-3.5" />Masked before reaching the AI</span>} />
                <Item label="Provider data retention" value="Disabled (store=false)" />
                <Item label="Safety buffer" value={`${p.safetyBufferWeeks} week of average outgoings`} />
              </dl>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Safety limits" subtitle="Enforced server-side for every action, whoever requests it" />
          <CardBody>
            {!p ? <Skeleton className="h-40" /> : (
              <dl className="divide-y divide-line">
                <Item label="Password re-confirmation" value={`for actions of ${money(p.reauthThreshold)}+`} />
                <Item label="Scheduled payment limit" value={`${money(p.schedulePaymentMax)} each`} />
                <Item label="Daily payment limit" value={money(p.schedulePaymentDailyMax)} />
                <Item label="Requests expire after" value={`${p.requestTtlHours} hours`} />
                <Item label="Money transfers to new payees" value={<Badge tone="danger">Not possible</Badge>} />
              </dl>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Permissions by role" subtitle="What each role can see and decide" />
          <CardBody className="overflow-x-auto">
            {!p ? <Skeleton className="h-40" /> : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted">
                    <th className="py-2 text-left font-medium">Capability</th>
                    {ROLES.map((r) => <th key={r} className="py-2 font-medium capitalize">{r}</th>)}
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {(["T0", "T1", "T2"] as Tier[]).map((t) => (
                    <tr key={t}>
                      <td className="py-2"><TierBadge tier={t} /> <span className="ml-1 text-xs text-muted">
                        {t === "T0" ? "read data" : t === "T1" ? "analysis & advice" : "request actions"}</span></td>
                      {ROLES.map((r) => <td key={r} className="py-2"><Yes on={p.roleTiers[r].includes(t)} /></td>)}
                    </tr>
                  ))}
                  {Object.entries(p.approverRoles).map(([action, roles]) => (
                    <tr key={action}>
                      <td className="py-2 text-xs text-ink">{ACTION_LABELS[action] ?? action}</td>
                      {ROLES.map((r) => <td key={r} className="py-2"><Yes on={roles.includes(r)} /></td>)}
                    </tr>
                  ))}
                  <tr>
                    <td className="py-2 text-xs text-ink">View the audit log</td>
                    {ROLES.map((r) => <td key={r} className="py-2"><Yes on={r !== "viewer"} /></td>)}
                  </tr>
                </tbody>
              </table>
            )}
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Agent tools" subtitle="The complete list of what the copilot can call. Anything else is refused." />
          <CardBody>
            {!p ? <Skeleton className="h-24" /> : (
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {p.tools.map((t) => (
                  <li key={t.name} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2">
                    <span className="truncate text-sm text-ink">{TOOL_LABELS[t.name] ?? t.name}</span>
                    <TierBadge tier={t.tier} />
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-4 flex items-center gap-1.5 text-xs text-muted">
              <ShieldCheck className="size-3.5" />T2 tools only create approval requests.
              <KeyRound className="ml-2 size-3.5" />Approval always happens here in the app, never inside the AI.
            </p>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
