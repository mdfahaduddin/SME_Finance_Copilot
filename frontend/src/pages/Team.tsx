import { Loader2, MailPlus, ShieldCheck, UserX, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { FormError, SelectField, TextField } from "../components/ui/Field";
import { PageHeader } from "../components/ui/PageHeader";
import { del, patch, post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { errorText, toast } from "../lib/toast";
import type { Role } from "../lib/types";
import { useApi } from "../lib/useApi";

interface Member { id: number; name: string; email: string; role: Role; active: boolean; mfaEnabled: boolean; you: boolean; lastLoginAt: string | null }
interface Invite { id: number; email: string; role: Role; expiresAt: string }

const ROLE_HELP: Record<Role, string> = {
  owner: "Everything, including approving payments and financing",
  accountant: "Import data, request actions, approve payment reminders",
  viewer: "Read-only access to dashboards and the copilot",
};

export default function Team() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const { data, reload } = useApi<{ members: Member[]; invites: Invite[] }>("/team");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("accountant");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function invite(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/team/invites", { email, role });
      toast.success("Invitation sent", `${email} can join as ${role}. The link is valid for 7 days.`);
      setEmail("");
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>, done: string) {
    try {
      await fn();
      await reload();
      toast.success(done);
    } catch (err) {
      toast.error("That change was not saved", errorText(err));
    }
  }

  return (
    <>
      <PageHeader title="Team" description="Who can see and act on your business finances." />
      <div className="grid gap-4 lg:grid-cols-5">
        <Card className="min-w-0 lg:col-span-3">
          <CardHeader title="Members" subtitle={`${data?.members.filter((m) => m.active).length ?? 0} active`} />
          <CardBody className="divide-y divide-line pt-2">
            {data?.members.map((m) => (
              <div key={m.id} className="flex flex-wrap items-center gap-3 py-3">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700 dark:bg-brand-900/50 dark:text-brand-200">
                  {m.name.split(" ").map((p) => p[0]).join("").slice(0, 2)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-1.5 text-sm font-medium text-ink">
                    {m.name}{m.you && <Badge tone="brand">you</Badge>}{!m.active && <Badge tone="danger">deactivated</Badge>}
                    {m.mfaEnabled && <Badge tone="success"><ShieldCheck className="size-3" />2FA</Badge>}
                  </p>
                  <p className="truncate text-xs text-muted">{m.email}{m.lastLoginAt && ` · last sign-in ${new Date(m.lastLoginAt).toLocaleDateString()}`}</p>
                </div>
                {isOwner && !m.you ? (
                  <div className="flex items-center gap-2">
                    <select value={m.role} aria-label={`Role of ${m.name}`} disabled={!m.active}
                      onChange={(e) => { const r = e.target.value; act(() => patch(`/team/members/${m.id}`, { role: r }), `${m.name} is now ${r === "accountant" ? "an" : "a"} ${r}`); }}
                      className="h-8 rounded-lg border border-line bg-surface px-2 text-xs text-ink focus:border-brand-500 focus:outline-none">
                      {(["owner", "accountant", "viewer"] as Role[]).map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <Button size="sm" variant="ghost" onClick={() => act(() => patch(`/team/members/${m.id}`, { active: !m.active }), `${m.name} ${m.active ? "deactivated" : "reactivated"}`)}
                      title={m.active ? "Deactivate (signs them out immediately)" : "Reactivate"}>
                      <UserX className="size-3.5" />{m.active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </div>
                ) : <Badge tone="neutral" className="capitalize">{m.role}</Badge>}
              </div>
            ))}
          </CardBody>
        </Card>

        <div className="min-w-0 space-y-4 lg:col-span-2">
          {isOwner && (
            <Card>
              <CardHeader title="Invite someone" subtitle="They'll get an email link valid for 7 days" />
              <CardBody>
                <form onSubmit={invite} className="space-y-3">
                  <TextField label="Email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
                  <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)} hint={ROLE_HELP[role]}>
                    <option value="accountant">Accountant</option>
                    <option value="viewer">Viewer</option>
                    <option value="owner">Owner</option>
                  </SelectField>
                  <Button type="submit" disabled={busy} className="w-full">
                    {busy ? <Loader2 className="size-4 animate-spin" /> : <MailPlus className="size-4" />} Send invitation
                  </Button>
                  <FormError message={error} />
                </form>
              </CardBody>
            </Card>
          )}
          {data && data.invites.length > 0 && (
            <Card>
              <CardHeader title="Pending invitations" />
              <CardBody className="divide-y divide-line pt-2">
                {data.invites.map((i) => (
                  <div key={i.id} className="flex items-center gap-2 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-ink">{i.email}</p>
                      <p className="text-xs text-muted capitalize">{i.role} · expires {new Date(i.expiresAt).toLocaleDateString()}</p>
                    </div>
                    {isOwner && (
                      <button onClick={() => act(() => del(`/team/invites/${i.id}`), `Invitation for ${i.email} cancelled`)} aria-label={`Cancel invitation for ${i.email}`}
                        className="grid size-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-danger">
                        <X className="size-4" />
                      </button>
                    )}
                  </div>
                ))}
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
