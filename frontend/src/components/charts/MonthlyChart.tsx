import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { money } from "../../lib/format";

export interface MonthPoint { month: string; partial: boolean; inflows: number; outflows: number; netCashFlow: number }

const label = (m: string) => new Date(m + "-01T00:00:00").toLocaleDateString("en-US", { month: "short" });

function MonthTooltip({ active, payload, currency }: { active?: boolean; payload?: { payload: MonthPoint }[]; currency: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const title = new Date(p.month + "-01T00:00:00").toLocaleDateString("en-US", { month: "long", year: "numeric" });
  return (
    <div className="min-w-44 rounded-xl border border-line bg-surface px-3 py-2.5 text-xs shadow-lg">
      <p className="mb-1.5 font-medium text-ink">{title}{p.partial && <span className="font-normal text-muted"> (so far)</span>}</p>
      <div className="flex justify-between gap-4 py-0.5"><span className="text-muted">Money in</span><span className="num text-ink">{money(p.inflows, currency)}</span></div>
      <div className="flex justify-between gap-4 py-0.5"><span className="text-muted">Money out</span><span className="num text-ink">{money(p.outflows, currency)}</span></div>
      <div className="mt-1 flex justify-between gap-4 border-t border-line pt-1.5">
        <span className="text-muted">Net</span>
        <span className={p.netCashFlow >= 0 ? "num font-semibold text-success" : "num font-semibold text-danger"}>{money(p.netCashFlow, currency)}</span>
      </div>
    </div>
  );
}

/** Money in vs money out per month (categorical slots 1 and 2); the current, partial month is drawn lighter. */
export function MonthlyChart({ months, currency, height = 240 }: { months: MonthPoint[]; currency: string; height?: number }) {
  const data = months.slice(-12);
  return (
    <div style={{ height }} role="img" aria-label="Monthly money in and money out for the last 12 months">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 4 }} barGap={2} barCategoryGap="28%">
          <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" />
          <XAxis dataKey="month" tickFormatter={label} tick={{ fontSize: 11, fill: "var(--color-muted)" }}
            axisLine={{ stroke: "var(--color-chart-axis)" }} tickLine={false} />
          <YAxis tickFormatter={(v: number) => money(v, currency, true)} tick={{ fontSize: 11, fill: "var(--color-muted)" }}
            axisLine={false} tickLine={false} width={56} />
          <Tooltip content={<MonthTooltip currency={currency} />} cursor={{ fill: "var(--color-surface-2)" }} />
          <Bar dataKey="inflows" name="Money in" fill="var(--color-chart-1)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.month} fillOpacity={d.partial ? 0.45 : 1} />)}
          </Bar>
          <Bar dataKey="outflows" name="Money out" fill="var(--color-chart-2)" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {data.map((d) => <Cell key={d.month} fillOpacity={d.partial ? 0.45 : 1} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function MonthlyLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-chart-1" />Money in</span>
      <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-chart-2" />Money out</span>
      <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm bg-chart-1/45" />Current month (so far)</span>
    </div>
  );
}
