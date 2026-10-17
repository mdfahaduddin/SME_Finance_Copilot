import { CheckCircle2, Download, FileSpreadsheet, FileText, Loader2, RotateCcw, Scale, TriangleAlert, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { upload } from "../../lib/api";
import { cn } from "../../lib/cn";
import { downloadFile } from "../../lib/download";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { FormError, SelectField, TextField } from "../ui/Field";
import { money } from "../../lib/format";
import { useApi } from "../../lib/useApi";
import { useAuth } from "../../lib/auth";
import { toast } from "../../lib/toast";

export type ImportKind = "transactions" | "invoices" | "bills";

interface Report {
  kind: ImportKind;
  fileName: string;
  dryRun: boolean;
  rowsTotal: number;
  imported: number;
  updated: number;
  duplicates: number;
  rejected: number;
  linkedPayments: number;
  errors: { row: number; label?: string; errors: string[] }[];
  columns: string[];
  preview: Record<string, string | number | boolean | null>[];
  warnings?: string[];
  statement?: StatementInfo | null;
}

/** What the server read from a PDF bank statement. */
interface StatementInfo {
  pages: number;
  periodStart: string;
  periodEnd: string;
  openingBalance: number | null;
  closingBalance: number | null;
  reconciledRows?: number;
  mismatchedRows?: number;
  ocrPages?: number[];
}

interface Account { id: number; name: string; type: string; number: string }

const KINDS: { key: ImportKind; label: string; help: string }[] = [
  { key: "transactions", label: "Bank transactions", help: "Upload the PDF statements from your bank (downloaded or scanned), or a CSV/Excel export. 6-12 months gives the best forecast." },
  { key: "invoices", label: "Customer invoices", help: "Open and paid invoices from your invoicing or accounting tool." },
  { key: "bills", label: "Supplier bills", help: "Bills you owe, with due dates, so the forecast knows what's coming." },
];

const DATE_FORMATS = ["auto", "YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"];

export function ImportPanel({ initialKind = "transactions", onImported }: { initialKind?: ImportKind; onImported?: () => void }) {
  const [kind, setKind] = useState<ImportKind>(initialKind);
  const [file, setFile] = useState<File | null>(null);
  const [dateFormat, setDateFormat] = useState("auto");
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState<"preview" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [password, setPassword] = useState("");
  const [accountId, setAccountId] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { data: accounts } = useApi<Account[]>("/ledger/accounts");
  const currency = useAuth().user?.business?.currency ?? "USD";
  const isPdf = !!file && file.name.toLowerCase().endsWith(".pdf");
  const chooseAccount = kind === "transactions" && (accounts?.length ?? 0) > 1;

  function reset(nextKind = kind) {
    setKind(nextKind);
    setFile(null);
    setReport(null);
    setError(null);
    setPassword("");
    if (inputRef.current) inputRef.current.value = "";
  }

  async function send(dryRun: boolean) {
    if (!file) return;
    setBusy(dryRun ? "preview" : "import");
    setError(null);
    const form = new FormData();
    form.append("file", file);
    form.append("dry_run", String(dryRun));
    form.append("date_format", dateFormat);
    if (isPdf && password) form.append("password", password);
    if (chooseAccount && accountId) form.append("account_id", accountId);
    try {
      const r = await upload<Report>(`/import/${kind}`, form);
      setReport(r);
      if (!dryRun) {
        onImported?.();
        const parts = [`${r.imported} new`, r.updated && `${r.updated} updated`, r.duplicates && `${r.duplicates} already there`,
          r.rejected && `${r.rejected} rejected`].filter(Boolean);
        toast.success(`Imported ${r.fileName}`, parts.join(" · "));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  function pick(f: File | undefined | null) {
    if (!f) return;
    setFile(f);
    setReport(null);
    setError(null);
    setPassword("");
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDrag(false);
    pick(e.dataTransfer.files?.[0]);
  }

  const done = report && !report.dryRun;
  const help = KINDS.find((k) => k.key === kind)!.help;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1 rounded-xl border border-line bg-surface-2/50 p-1" role="tablist">
        {KINDS.map((k) => (
          <button key={k.key} role="tab" aria-selected={kind === k.key} onClick={() => reset(k.key)}
            className={cn("flex-1 rounded-lg px-3 py-1.5 text-sm font-medium whitespace-nowrap transition-colors",
              kind === k.key ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink")}>
            {k.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">{help}</p>
        <Button size="sm" variant="ghost" onClick={() => downloadFile(`/import/templates/${kind}.csv`, `${kind}-template.csv`)}>
          <Download className="size-3.5" /> Template
        </Button>
      </div>

      {done ? (
        <div className="rounded-xl border border-success/30 bg-success-soft/50 p-4">
          <p className="flex items-center gap-2 text-sm font-semibold text-ink"><CheckCircle2 className="size-4 text-success" />
            Imported {report.imported} new {report.updated ? `and updated ${report.updated} ` : ""}rows from {report.fileName}
          </p>
          <p className="mt-1 text-xs text-muted">
            {report.duplicates} duplicates skipped · {report.rejected} rows rejected
            {report.linkedPayments ? ` · ${report.linkedPayments} payments matched to invoices` : ""}
          </p>
          <Button size="sm" variant="secondary" className="mt-3" onClick={() => reset()}><RotateCcw className="size-3.5" /> Import another file</Button>
        </div>
      ) : (
        <>
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
            role="button"
            tabIndex={0}
            className={cn("flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed px-6 py-8 text-center transition-colors",
              drag ? "border-brand-500 bg-brand-50 dark:bg-brand-900/20" : "border-line hover:border-brand-300")}
          >
            {isPdf ? <FileText className="size-8 text-brand-600" />
              : file ? <FileSpreadsheet className="size-8 text-brand-600" /> : <Upload className="size-8 text-muted" />}
            <p className="text-sm font-medium text-ink">
              {file ? file.name : kind === "transactions" ? "Drop a PDF statement, CSV or Excel file, or click to choose" : "Drop a CSV or Excel file, or click to choose"}
            </p>
            <p className="text-xs text-muted">
              {file ? `${(file.size / 1024).toFixed(0)} KB` : kind === "transactions" ? ".pdf, .csv or .xlsx, up to 5 MB" : ".csv or .xlsx, up to 5 MB"}
            </p>
            <input ref={inputRef} type="file" className="hidden" onChange={(e) => pick(e.target.files?.[0])}
              accept={kind === "transactions" ? ".pdf,.csv,.xlsx,application/pdf,text/csv" : ".csv,.xlsx,text/csv"} />
          </div>

          {/* Top-aligned so the inputs line up even when the hints below them differ in length. */}
          <div className="flex flex-wrap items-start gap-3">
            {chooseAccount && (
              <SelectField label="Into account" value={accountId} onChange={(e) => { setAccountId(e.target.value); setReport(null); }}
                className="w-56" hint="Which account this is for">
                <option value="">Main checking account</option>
                {accounts!.map((a) => <option key={a.id} value={a.id}>{a.name} {a.number}</option>)}
              </SelectField>
            )}
            {isPdf && (
              <TextField label="PDF password" type="password" autoComplete="off" value={password} className="w-48"
                onChange={(e) => { setPassword(e.target.value); setReport(null); }}
                hint="Only if the file is protected" />
            )}
            <SelectField label="Date format" value={dateFormat} onChange={(e) => setDateFormat(e.target.value)} className="w-48"
              hint="Pick one if dates are ambiguous">
              {DATE_FORMATS.map((f) => <option key={f} value={f}>{f === "auto" ? "Detect automatically" : f}</option>)}
            </SelectField>
            {/* Label height (26px) minus half the 3px height difference: buttons centred on the input row. */}
            <div className="ml-auto flex gap-2 sm:mt-6">
              <Button variant="secondary" onClick={() => send(true)} disabled={!file || !!busy}>
                {busy === "preview" && <Loader2 className="size-4 animate-spin" />} Check file
              </Button>
              <Button onClick={() => send(false)} disabled={!report || !!busy || report.imported + report.updated === 0}>
                {busy === "import" ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />} Import
              </Button>
            </div>
          </div>
        </>
      )}

      {busy === "preview" && isPdf && (
        <p className="text-xs text-muted">Reading the statement. Scanned pages can take up to a minute.</p>
      )}

      <FormError message={error} />

      {report?.dryRun && (
        <div className="space-y-3 rounded-xl border border-line p-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="font-semibold text-ink">Preview of {report.rowsTotal} rows:</span>
            <Badge tone="success">{report.imported} new</Badge>
            {report.updated > 0 && <Badge tone="info">{report.updated} updates</Badge>}
            {report.duplicates > 0 && <Badge tone="neutral">{report.duplicates} already imported</Badge>}
            {report.rejected > 0 && <Badge tone="danger">{report.rejected} with errors</Badge>}
          </div>
          {report.statement && <StatementSummary info={report.statement} currency={currency} />}
          {report.warnings?.map((w) => (
            <p key={w} className="flex items-start gap-1.5 rounded-lg bg-warning-soft px-3 py-2 text-xs text-ink">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />{w}
            </p>
          ))}
          {report.preview.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="w-full min-w-[32rem] text-xs">
                <thead className="bg-surface-2 text-left text-muted">
                  <tr>{Object.keys(report.preview[0]).map((k) => <th key={k} className="px-2.5 py-1.5 font-medium">{k}</th>)}</tr>
                </thead>
                <tbody>
                  {report.preview.slice(0, 5).map((row, i) => (
                    <tr key={i} className="border-t border-line">
                      {Object.values(row).map((v, j) => <td key={j} className="max-w-48 truncate px-2.5 py-1.5 text-ink">{String(v ?? "")}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {report.errors.length > 0 && (
            <div>
              <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-danger"><TriangleAlert className="size-3.5" />
                Rows that will be skipped (fix them in the file and import again):
              </p>
              <ul className="max-h-40 space-y-0.5 overflow-y-auto text-xs text-muted">
                {report.errors.map((e, i) => <li key={i}>{e.label ?? `Row ${e.row}`}: {e.errors.join("; ")}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatementSummary({ info, currency }: { info: StatementInfo; currency: string }) {
  const checked = (info.reconciledRows ?? 0) + (info.mismatchedRows ?? 0);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg bg-surface-2/60 px-3 py-2 text-xs text-muted">
      <span><span className="font-medium text-ink">Statement</span> {info.periodStart} to {info.periodEnd} · {info.pages} page{info.pages === 1 ? "" : "s"}</span>
      {!!info.ocrPages?.length && <Badge tone="warning">Read from a scan (OCR)</Badge>}
      {info.openingBalance !== null && <span>Opening <span className="num text-ink">{money(info.openingBalance, currency)}</span></span>}
      {info.closingBalance !== null && <span>Closing <span className="num text-ink">{money(info.closingBalance, currency)}</span></span>}
      {checked > 0 && (
        <span className="flex items-center gap-1">
          <Scale className="size-3.5" />
          {info.mismatchedRows
            ? <Badge tone="warning">{info.mismatchedRows} of {checked} rows don't match the balance</Badge>
            : <Badge tone="success">All {checked} rows match the running balance</Badge>}
        </span>
      )}
    </div>
  );
}
