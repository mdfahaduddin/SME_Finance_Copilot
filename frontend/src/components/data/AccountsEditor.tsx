import { Landmark, Loader2, Pencil, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, post, put } from "../../lib/api";
import { money } from "../../lib/format";
import { toast } from "../../lib/toast";
import { useApi } from "../../lib/useApi";
import { Button } from "../ui/Button";
import { FormError, SelectField, TextField } from "../ui/Field";

interface Account { id: number; name: string; type: "checking" | "savings"; number: string; balance: number; currency: string }

export function AccountsEditor({ canEdit, onChange }: { canEdit: boolean; onChange?: (count: number) => void }) {
  const { data: accounts, reload } = useApi<Account[]>("/ledger/accounts");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "Operating account", accountType: "checking", last4: "", balance: "" });
  const [editing, setEditing] = useState<{ id: number; balance: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    await reload();
    const list = await api<Account[]>("/ledger/accounts");
    onChange?.(list.length);
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/business/accounts", { ...form, balance: Number(form.balance) });
      toast.success(`${form.name} added`);
      setAdding(false);
      setForm({ name: "Savings account", accountType: "savings", last4: "", balance: "" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveBalance(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setBusy(true);
    setError(null);
    try {
      await put(`/business/accounts/${editing.id}`, { balance: Number(editing.balance) });
      toast.success("Balance updated");
      setEditing(null);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const empty = accounts && accounts.length === 0;

  return (
    <div className="space-y-3">
      {accounts?.map((a) => (
        <div key={a.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-line p-3">
          <span className="grid size-9 place-items-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/40 dark:text-brand-300">
            <Landmark className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-ink">{a.name}</p>
            <p className="text-xs text-muted capitalize">{a.type}{a.number !== "****" && ` · ${a.number}`}</p>
          </div>
          {editing?.id === a.id ? (
            // Own full-width line: sharing the row with the name squeezed both out of the card.
            <form onSubmit={saveBalance} className="basis-full border-t border-line pt-3">
              <label htmlFor={`balance-${a.id}`} className="text-xs font-medium text-muted">
                New balance <span className="font-normal">(was {money(a.balance, a.currency)})</span>
              </label>
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <div className="relative min-w-0 flex-1 basis-36">
                  <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-xs font-medium text-muted">
                    {a.currency}
                  </span>
                  <input id={`balance-${a.id}`} type="number" step="0.01" required autoFocus value={editing.balance}
                    onChange={(e) => setEditing({ id: a.id, balance: e.target.value })}
                    onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                    className="num h-9 w-full rounded-lg border border-line bg-surface pr-3 pl-12 text-sm text-ink focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20 focus:outline-none" />
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button size="sm" type="submit" disabled={busy} className="h-9">
                    {busy && <Loader2 className="size-3.5 animate-spin" />} Save
                  </Button>
                  <Button size="sm" variant="ghost" type="button" className="h-9" onClick={() => setEditing(null)}>Cancel</Button>
                </div>
              </div>
            </form>
          ) : (
            <>
              <p className="num text-sm font-semibold text-ink">{money(a.balance, a.currency)}</p>
              {canEdit && (
                <button onClick={() => setEditing({ id: a.id, balance: String(a.balance) })} aria-label={`Update balance of ${a.name}`}
                  className="grid size-8 place-items-center rounded-lg text-muted hover:bg-surface-2 hover:text-ink">
                  <Pencil className="size-3.5" />
                </button>
              )}
            </>
          )}
        </div>
      ))}

      {canEdit && (adding || empty) ? (
        <form onSubmit={add} className="grid gap-3 rounded-xl border border-dashed border-line p-4 sm:grid-cols-2">
          <TextField label="Account name" required minLength={2} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <SelectField label="Type" value={form.accountType} onChange={(e) => setForm({ ...form, accountType: e.target.value })}>
            <option value="checking">Checking / current (day-to-day)</option>
            <option value="savings">Savings / reserve</option>
          </SelectField>
          <TextField label="Current balance" type="number" step="0.01" required value={form.balance}
            onChange={(e) => setForm({ ...form, balance: e.target.value })} hint="Today's balance from your banking app" />
          <TextField label="Last 4 digits (optional)" inputMode="numeric" pattern="\d{4}" maxLength={4} value={form.last4}
            onChange={(e) => setForm({ ...form, last4: e.target.value.replace(/\D/g, "") })} hint="We never store full account numbers" />
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={busy}>{busy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />} Add account</Button>
            {!empty && <Button type="button" variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>}
          </div>
        </form>
      ) : canEdit && (
        <Button variant="secondary" size="sm" onClick={() => setAdding(true)}><Plus className="size-3.5" /> Add another account</Button>
      )}
      <FormError message={error} />
    </div>
  );
}
