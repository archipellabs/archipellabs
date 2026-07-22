/* Portal UI kit — the six components the portal uses, reimplemented locally so it
 * no longer depends on the vendored @archipellabs/design-system package. Styling
 * lives in ui.css (tokens + classes); this file is just the markup. */
import type { CSSProperties, ElementType, ReactNode } from "react";

/* ---- Root: the app container that carries the base typography + reset ---- */
export function Root({
  theme = "light",
  children,
}: {
  theme?: "light" | "dark";
  children: ReactNode;
}) {
  return (
    <div className="apl-root" data-theme={theme}>
      {children}
    </div>
  );
}

/* ---- Stack: a flex row/column with token-scale gaps ---- */
type Space = "2xs" | "xs" | "sm" | "md" | "lg" | "xl" | "2xl";
type Justify = "start" | "center" | "end" | "between" | "around";
type Align = "start" | "center" | "end" | "stretch" | "baseline";

const JUSTIFY: Record<Justify, string> = {
  start: "flex-start",
  center: "center",
  end: "flex-end",
  between: "space-between",
  around: "space-around",
};
const ALIGN: Record<Align, string> = {
  start: "flex-start",
  center: "center",
  end: "flex-end",
  stretch: "stretch",
  baseline: "baseline",
};

export function Stack({
  direction = "row",
  gap,
  justify,
  align,
  wrap = false,
  children,
}: {
  direction?: "row" | "column";
  gap?: Space;
  justify?: Justify;
  align?: Align;
  wrap?: boolean;
  children: ReactNode;
}) {
  const style: CSSProperties = {
    display: "flex",
    flexDirection: direction,
    gap: gap ? `var(--space-${gap})` : undefined,
    justifyContent: justify ? JUSTIFY[justify] : undefined,
    alignItems: align ? ALIGN[align] : undefined,
    flexWrap: wrap ? "wrap" : undefined,
  };
  return (
    <div className="apl-stack" style={style}>
      {children}
    </div>
  );
}

/* ---- Text: a semantic element styled by variant + optional ink color ---- */
type TextVariant = "overline" | "h1" | "h2" | "h3" | "title" | "body" | "small";
type TextColor = "brand" | "muted" | "danger" | "heading" | "subtle";

const TEXT_TAG: Record<TextVariant, ElementType> = {
  overline: "div",
  h1: "h1",
  h2: "h2",
  h3: "h3",
  title: "p",
  body: "p",
  small: "p",
};

export function Text({
  variant = "body",
  color,
  as,
  children,
}: {
  variant?: TextVariant;
  color?: TextColor;
  as?: ElementType;
  children: ReactNode;
}) {
  const Tag = as ?? TEXT_TAG[variant] ?? "p";
  const cls = ["apl-text", `apl-text--${variant}`, color ? `apl-text--c-${color}` : ""]
    .filter(Boolean)
    .join(" ");
  return <Tag className={cls}>{children}</Tag>;
}

/* ---- Badge: a pill; the portal uses solid/success/sm ---- */
export function Badge({
  appearance = "soft",
  tone = "neutral",
  size,
  children,
}: {
  appearance?: "soft" | "solid" | "outline";
  tone?: "neutral" | "brand" | "accent" | "success" | "warning" | "danger" | "info";
  size?: "sm";
  children: ReactNode;
}) {
  const cls = [
    "apl-badge",
    `apl-badge--${appearance}`,
    `apl-badge--${tone}`,
    size ? `apl-badge--${size}` : "",
  ]
    .filter(Boolean)
    .join(" ");
  return <span className={cls}>{children}</span>;
}

/* ---- Card + Card.Body ---- */
function CardBody({ children }: { children: ReactNode }) {
  return <div className="apl-card__body">{children}</div>;
}
function CardRoot({
  variant = "outlined",
  children,
}: {
  variant?: "outlined" | "plate" | "plain" | "elevated";
  children: ReactNode;
}) {
  return <div className={`apl-card apl-card--${variant}`}>{children}</div>;
}
// Card is a component (compound with Card.Body); Object.assign hides that from the
// react-refresh heuristic, so opt this one export out.
// eslint-disable-next-line react-refresh/only-export-components
export const Card = Object.assign(CardRoot, { Body: CardBody });

/* ---- Stat: a KPI readout ---- */
export function Stat({
  label,
  value,
  unit,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
}) {
  return (
    <div className="apl-stat">
      <div className="apl-stat__label">{label}</div>
      <div className="apl-stat__readout">
        <span className="apl-stat__value">{value}</span>
        {unit ? <span className="apl-stat__unit">{unit}</span> : null}
      </div>
    </div>
  );
}
