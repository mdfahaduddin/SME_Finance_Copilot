import { Loader2, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { put } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { toast } from "../../lib/toast";
import { useApi } from "../../lib/useApi";
import { Button } from "../ui/Button";
import { Card, CardBody, CardHeader } from "../ui/Card";
import { FormError, SelectField, TextField } from "../ui/Field";

interface Profile {
  name: string; industry: string; region: string; foundedDate: string; employees: number; currency: string;
  creditScore: number | null; hasCollateral: boolean; annualRevenue: number; industries: string[];
}

/** Business details used by financing eligibility and the copilot. Editable by owners. */
export function BusinessProfileCard() {
  const { user, refresh } = useAuth();
  const { data } = useApi<Profile>("/business/profile");
  const [form, setForm] = useState<Profile | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canEdit = user?.role === "owner";

  useEffect(() => { if (data) setForm(data); }, [data]);
  if (!form) return null;

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setForm({ ...form, [k]: v });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      // Send only the editable fields: the GET response also carries read-only ones (id, onboardingStatus,
      // industries...) and the API rejects unknown fields.
      const body = {
        name: form.name, industry: form.industry, region: form.region, foundedDate: form.foundedDate,
        employees: form.employees, currency: form.currency, creditScore: form.creditScore, hasCollateral: form.hasCollateral,
      };
      await put("/business/profile", body);
      await refresh();
      toast.success("Business profile saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader title="Business profile" subtitle="Used for financing eligibility. A credit score gives sharper rate estimates." />
      <CardBody>
        <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <TextField label="Business name" required disabled={!canEdit} value={form.name} onChange={(e) => set("name", e.target.value)} className="sm:col-span-2" />
          <SelectField label="Industry" disabled={!canEdit} value={form.industry} onChange={(e) => set("industry", e.target.value)}>
            {form.industries.map((i) => <option key={i}>{i}</option>)}
          </SelectField>
          <TextField label="City / region" disabled={!canEdit} value={form.region} onChange={(e) => set("region", e.target.value)} />
          <TextField label="Founded" type="date" required disabled={!canEdit} value={form.foundedDate} onChange={(e) => set("foundedDate", e.target.value)} />
          <TextField label="Employees" type="number" min={0} disabled={!canEdit} value={form.employees} onChange={(e) => set("employees", Number(e.target.value))} />
          <TextField label="Business credit score" type="number" min={300} max={850} disabled={!canEdit}
            value={form.creditScore ?? ""} placeholder="Not provided" hint="300-850, optional"
            onChange={(e) => set("creditScore", e.target.value ? Number(e.target.value) : null)} />
          <label className="flex items-center gap-2 self-center pt-5 text-sm text-ink">
            <input type="checkbox" disabled={!canEdit} checked={form.hasCollateral} onChange={(e) => set("hasCollateral", e.target.checked)}
              className="size-4 accent-brand-600" />
            Can offer collateral (property, equipment)
          </label>
          {canEdit && (
            <div className="flex items-center gap-3 sm:col-span-2 lg:col-span-4">
              <Button type="submit" size="sm" disabled={busy}>{busy ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />} Save profile</Button>
              <FormError message={error} />
            </div>
          )}
        </form>
      </CardBody>
    </Card>
  );
}
