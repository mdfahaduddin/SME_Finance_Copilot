import {
  Area, CartesianGrid, ComposedChart, Line, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { money } from "../../lib/format";

export interface ForecastPoint {
  week: number;
  start: string;
  closing: number;
  p10: number;
  p90: number;
  inflows?: number;
  outflows?: number;
}

interface Props {
  weeks: ForecastPoint[];
  buffer: number;
  height?: number;
  /** Optional comparison line (what-if scenario); the baseline is then drawn muted. */
  scenario?: { week: number; value: number }[];
  scenarioLabel?: string;
  currency?: string;
}

const short = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });

function compactIn(currency?: string) {
  return (v: number) => money(v, currency, true);
}

interface TipProps {
  active?: boolean;
  payload?: { payload: ForecastPoint & { scenario?: number } }[];
  scenarioLabel?: string;
  currency?: string;
}

function ForecastTooltip({ active, payload, scenarioLabel, currency }: TipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  const m = (v: number) => money(v, currency);
  return (
    <div className="min-w-48 rounded-xl border border-line bg-surface px-3 py-2.5 text-xs shadow-lg">
      <p className="mb-1.5 font-medium text-ink">Week {p.week} · {short(p.start)}</p>
      <Row label={p.scenario !== undefined ? "Baseline" : "Projected balance"} value={m(p.closing)} strong={p.scenario === undefined} />
      {p.scenario !== undefined && <Row label={scenarioLabel ?? "Scenario"} value={m(p.scenario)} strong />}
      <Row label="80% range" value={`${m(p.p10)} to ${m(p.p90)}`} />
      {p.inflows !== undefined && <Row label="In / out" value={`${m(p.inflows)} / ${m(p.outflows ?? 0)}`} />}
    </div>
  );
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="flex justify-between gap-4 py-0.5">
      <span className="text-muted">{label}</span>
      <span className={strong ? "num font-semibold text-ink" : "num text-ink"}>{value}</span>
    </div>
  );
}

/**
 * 13-week projected operating balance: one line (slot 1), the P10-P90 band as a light wash of the same hue,
 * the safety buffer as a labelled threshold, and a single direct label on the lowest point.
 */
export function ForecastChart({ weeks, buffer, height = 260, scenario, scenarioLabel, currency }: Props) {
  const compact = compactIn(currency);
  const data = weeks.map((w) => ({
    ...w,
    band: [w.p10, w.p90] as [number, number],
    scenario: scenario?.find((s) => s.week === w.week)?.value,
  }));
  const series = scenario ? "scenario" : "closing";
  const lowest = data.reduce((lo, d) => ((d[series] ?? Infinity) < (lo[series] ?? Infinity) ? d : lo), data[0]);
  const lowestValue = (lowest?.[series] as number | undefined) ?? 0;

  return (
    <div style={{ height }} role="img" aria-label={`13-week cash forecast; lowest ${money(lowestValue, currency)} in week ${lowest?.week}`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 22, right: 12, bottom: 0, left: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--color-chart-grid)" />
          <XAxis dataKey="start" tickFormatter={short} tick={{ fontSize: 11, fill: "var(--color-muted)" }}
            axisLine={{ stroke: "var(--color-chart-axis)" }} tickLine={false} minTickGap={24} />
          <YAxis tickFormatter={compact} tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false}
            tickLine={false} width={52} />
          <Tooltip content={<ForecastTooltip scenarioLabel={scenarioLabel} currency={currency} />}
            cursor={{ stroke: "var(--color-muted)", strokeWidth: 1 }} />
          {!scenario && (
            <Area dataKey="band" stroke="none" fill="var(--color-chart-band)" isAnimationActive={false} activeDot={false} />
          )}
          <ReferenceLine y={0} stroke="var(--color-chart-axis)" />
          <ReferenceLine y={buffer} stroke="var(--color-warning)" strokeDasharray="4 4" strokeWidth={1.5}
            label={{ value: `Safety buffer ${compact(buffer)}`, position: "insideTopRight", fontSize: 11, fill: "var(--color-warning)" }} />
          <Line dataKey="closing" type="monotone" strokeWidth={2} isAnimationActive={false}
            stroke={scenario ? "var(--color-muted)" : "var(--color-chart-1)"} strokeOpacity={scenario ? 0.7 : 1}
            dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--color-surface)" }} />
          {scenario && (
            <Line dataKey="scenario" type="monotone" strokeWidth={2} stroke="var(--color-chart-1)" isAnimationActive={false}
              dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--color-surface)" }} />
          )}
          {lowest && (
            <ReferenceDot x={lowest.start} y={lowestValue} r={5} fill={lowestValue < buffer ? "var(--color-danger)" : "var(--color-chart-1)"}
              stroke="var(--color-surface)" strokeWidth={2}
              label={{ value: `Low ${compact(lowestValue)}`, position: "top", fontSize: 11, fontWeight: 600, fill: "var(--color-ink)" }} />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Text key for the forecast chart (identity never relies on color alone). */
export function ForecastLegend({ scenarioLabel }: { scenarioLabel?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
      {scenarioLabel ? (
        <>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-chart-1" />{scenarioLabel}</span>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-muted/70" />Baseline</span>
        </>
      ) : (
        <>
          <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 rounded bg-chart-1" />Projected balance</span>
          <span className="flex items-center gap-1.5"><span className="h-2.5 w-4 rounded-sm bg-chart-band" />80% range (P10 to P90)</span>
        </>
      )}
      <span className="flex items-center gap-1.5"><span className="w-4 border-t-[1.5px] border-dashed border-warning" />Safety buffer</span>
    </div>
  );
}
