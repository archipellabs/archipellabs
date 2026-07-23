import { type MouseEvent, type ReactNode, useState } from "react";
import { Card, Stack, Stat, Text } from "../ui";
import "./charts.css";

/* --- KPI stat in a card ---------------------------------------------------- */
export function StatCard({
  label,
  value,
  unit,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
}) {
  return (
    <Card variant="plate">
      <Card.Body>
        <Stat label={label} value={value} unit={unit} />
      </Card.Body>
    </Card>
  );
}

/* --- shared hover tooltip -------------------------------------------------- */
interface Tip {
  x: number;
  y: number;
  content: ReactNode;
}

function useTooltip() {
  const [tip, setTip] = useState<Tip | null>(null);
  const bind = (content: ReactNode) => ({
    onMouseEnter: (e: MouseEvent) => setTip({ x: e.clientX, y: e.clientY, content }),
    onMouseMove: (e: MouseEvent) =>
      setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t)),
    onMouseLeave: () => setTip(null),
  });
  const layer = tip ? (
    <div className="chart-tip" style={{ left: tip.x, top: tip.y }}>
      {tip.content}
    </div>
  ) : null;
  return { bind, layer };
}

/* --- panel + data table ---------------------------------------------------- */
export function Panel({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card variant="plate">
      <Card.Body>
        <Stack direction="column" gap="md">
          <Stack direction="column" gap="2xs">
            <Text variant="overline" color="muted">
              {eyebrow}
            </Text>
            <Text variant="title" as="h2">
              {title}
            </Text>
          </Stack>
          {children}
        </Stack>
      </Card.Body>
    </Card>
  );
}

export function DataTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: (string | number)[][];
}) {
  return (
    <details className="chart-data">
      <summary>Data table</summary>
      <table className="chart-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

/* --- proportion bar (multi-category outcome) ------------------------------- */
export interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
}

export function ProportionBar({ segments }: { segments: Segment[] }) {
  const { bind, layer } = useTooltip();
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  return (
    <div>
      <div className="prop-bar">
        {segments
          .filter((s) => s.value > 0)
          .map((s) => {
            const pct = (s.value / total) * 100;
            return (
              <div
                key={s.key}
                className="prop-seg"
                style={{ width: `${pct}%`, background: s.color }}
                {...bind(`${s.label}: ${s.value} · ${Math.round(pct)}%`)}
              />
            );
          })}
      </div>
      <div className="chart-legend">
        {segments.map((s) => (
          <span key={s.key} className="legend-item">
            <span className="legend-swatch" style={{ background: s.color }} />
            <span className="legend-label">{s.label}</span>
            <span className="legend-value">
              {s.value} · {Math.round((s.value / total) * 100)}%
            </span>
          </span>
        ))}
      </div>
      {layer}
    </div>
  );
}

/* --- horizontal bar list (single-series magnitude) ------------------------- */
export interface BarItem {
  key: string;
  label: string;
  value: number;
}

export function BarList({ items }: { items: BarItem[] }) {
  const { bind, layer } = useTooltip();
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="bar-list">
      {items.map((i) => (
        <div key={i.key} className="bar-row" {...bind(`${i.label}: ${i.value}`)}>
          <span className="bar-row__label" title={i.label}>
            {i.label}
          </span>
          <span className="bar-row__track">
            <span
              className="bar-row__fill"
              style={{ width: `${(i.value / max) * 100}%` }}
            />
          </span>
          <span className="bar-row__value">{i.value}</span>
        </div>
      ))}
      {layer}
    </div>
  );
}

/* --- column chart (change over time) --------------------------------------- */
export interface ColumnDatum {
  label: string; // full label, shown in the tooltip
  value: number;
  tick?: string; // axis label; omit to leave the axis blank (thins dense series)
}

export function ColumnChart({ data }: { data: ColumnDatum[] }) {
  const { bind, layer } = useTooltip();
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <div className="col-chart">
      {/* Bars sit on a shared baseline; the axis ticks live in their own aligned
          row below so sparse labels never collide with the zero-height columns. */}
      <div className="col-chart__plot">
        {data.map((d, i) => (
          <div
            key={`${d.label}-${i}`}
            className="col"
            {...bind(`${d.label}: ${d.value}`)}
          >
            <span
              className="col__bar"
              style={{ height: `${(d.value / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="col-chart__axis" aria-hidden="true">
        {data.map((d, i) => (
          <span key={`${d.label}-${i}`} className="col__label">
            {d.tick ?? ""}
          </span>
        ))}
      </div>
      {layer}
    </div>
  );
}
