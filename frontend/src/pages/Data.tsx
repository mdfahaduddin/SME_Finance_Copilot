import { CheckCircle2, History, TriangleAlert } from "lucide-react";
import { AccountsEditor } from "../components/data/AccountsEditor";
import { ImportPanel } from "../components/data/ImportPanel";
import { Badge } from "../components/ui/Badge";
import { Card, CardBody, CardHeader } from "../components/ui/Card";
import { PageHeader } from "../components/ui/PageHeader";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/useApi";

interface Batch {
  id: number; kind: string; fileName: string; rowsTotal: number; imported: number; duplicates: number; rejected: number;
  errors: { row: number; errors: string[] }[]; createdAt: string;
}

export default function Data() {
  const { user } = useAuth();
  const canEdit = user?.role === "owner" || user?.role === "accountant";
  const { data: history, reload } = useApi<Batch[]>("/import/history");

  return (
    <>
      <PageHeader title="Data" description="Your bank accounts and the data the copilot analyses. Import new statements any time; duplicates are skipped." />
      <div className="grid gap-4 xl:grid-cols-5">
        <div className="min-w-0 space-y-4 xl:col-span-3">
          <Card>
            <CardHeader title="Import" subtitle="PDF statements or CSV/Excel from your bank, invoicing or accounting software" />
            <CardBody>
              {canEdit ? <ImportPanel onImported={() => void reload()} />
                : <p className="text-sm text-muted">Only owners and accountants can import data.</p>}
            </CardBody>
          </Card>
        </div>
        <div className="min-w-0 space-y-4 xl:col-span-2">
          <Card>
            <CardHeader title="Bank accounts" subtitle="Keep balances current for an accurate forecast" />
            <CardBody><AccountsEditor canEdit={canEdit} /></CardBody>
          </Card>
          <Card>
            <CardHeader title="Import history" />
            <CardBody className="pt-3">
              {!history?.length && <p className="flex items-center gap-2 text-sm text-muted"><History className="size-4" /> No imports yet.</p>}
              <ul className="divide-y divide-line">
                {history?.map((b) => (
                  <li key={b.id} className="py-2.5">
                    <div className="flex items-center gap-2">
                      {b.rejected ? <TriangleAlert className="size-4 shrink-0 text-warning" /> : <CheckCircle2 className="size-4 shrink-0 text-success" />}
                      <p className="min-w-0 flex-1 truncate text-sm font-medium text-ink">{b.fileName}</p>
                      <Badge tone="neutral" className="capitalize">{b.kind}</Badge>
                    </div>
                    <p className="mt-0.5 pl-6 text-xs text-muted">
                      {new Date(b.createdAt).toLocaleString()} · {b.imported} imported · {b.duplicates} duplicates · {b.rejected} rejected
                    </p>
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
