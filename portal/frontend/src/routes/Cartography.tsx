import { type MouseEvent, useEffect, useState } from "react";
import { Stack, Text } from "../ui";
import {
  getCartography,
  type CartoApp,
  type CartoFlow,
  type Cartography as Data,
} from "../api";
import "./cartography.css";

const THUMB = (t?: string) => `/thumbs/${t}.png`;

const ENTERPRISE_NOTE =
  "demo credentials in each card’s Info · a dedicated read-only user is planned";

// Below this width we drop the sea-chart (arrows + absolute layout) for a plain
// vertical stack of cards — easier to read on a phone.
function useNarrow(max = 820) {
  const q = `(max-width: ${max}px)`;
  const [narrow, setNarrow] = useState(
    () => typeof window !== "undefined" && window.matchMedia(q).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(q);
    const on = () => setNarrow(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [q]);
  return narrow;
}

// Fixed island layout on the 1240×1000 sea-chart (stage-local coordinates).
const LAYOUT: Record<string, { x: number; y: number; w: number }> = {
  storefront: { x: 460, y: 40, w: 320 },
  backoffice: { x: 320, y: 460, w: 290 },
  analytics: { x: 700, y: 460, w: 290 },
  // roadmap wraps onto two rows: 4 up top, 3 below
  pim: { x: 110, y: 838, w: 150 },
  erp: { x: 300, y: 838, w: 150 },
  inventory: { x: 490, y: 838, w: 150 },
  accounting: { x: 680, y: 838, w: 150 },
  suppliers: { x: 110, y: 946, w: 150 },
  pos: { x: 300, y: 946, w: 150 },
  stores: { x: 490, y: 946, w: 150 },
};

// Hand-routed sea-lanes + label anchors (keyed "from-to").
const PATHS: Record<string, { d: string; lx: number; ly: number }> = {
  "storefront-analytics": { d: "M700,325 C 752,385 812,425 845,456", lx: 762, ly: 362 },
  "storefront-backoffice": { d: "M540,325 C 500,385 470,425 465,456", lx: 388, ly: 362 },
  "pim-backoffice": { d: "M190,832 C 240,818 320,795 380,752", lx: 238, ly: 772 },
  "backoffice-erp": { d: "M430,752 C 415,792 388,815 375,832", lx: 428, ly: 772 },
};

const SHIELD = (
  <svg width="11" height="13" viewBox="0 0 24 28" style={{ verticalAlign: -1 }}>
    <path
      d="M12 2 L22 6 V14 C22 21 12 26 12 26 C12 26 2 21 2 14 V6 Z"
      fill="none"
      stroke="var(--brass-500)"
      strokeWidth="2.4"
    />
  </svg>
);

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  // reset the label a moment after a successful copy; timer is cleaned up so it
  // never fires on an unmounted drawer.
  useEffect(() => {
    if (!done) return;
    const t = setTimeout(() => setDone(false), 1200);
    return () => clearTimeout(t);
  }, [done]);
  return (
    <button
      className="carto-copy-btn"
      onClick={() => {
        // only confirm when the write actually resolves (no clipboard API -> no-op)
        navigator.clipboard
          ?.writeText(text)
          .then(() => setDone(true))
          .catch(() => {});
      }}
    >
      {done ? "copied ✓" : "copy"}
    </button>
  );
}

function Flow({ flow }: { flow: CartoFlow }) {
  const p = PATHS[`${flow.from}-${flow.to}`];
  if (!p) return null;
  const marker = flow.kind === "live" ? "url(#carto-mg)" : "url(#carto-mp)";
  return (
    <g className={`carto-flow ${flow.kind === "live" ? "live" : "plan"}`}>
      <path className="carto-hit" d={p.d} />
      <path
        className="carto-lane"
        d={p.d}
        markerEnd={marker}
        markerStart={flow.bidir ? marker : undefined}
      />
      <text className="carto-flowlabel" x={p.lx} y={p.ly}>
        {flow.label}
      </text>
    </g>
  );
}

function AppCard({
  app,
  onInfo,
  chart = true,
}: {
  app: CartoApp;
  onInfo: (a: CartoApp) => void;
  chart?: boolean;
}) {
  const pos = LAYOUT[app.id];
  if (chart && !pos) return null;
  // in the chart the card is absolutely positioned; in the mobile list it flows.
  const style = chart && pos ? { left: pos.x, top: pos.y, width: pos.w } : undefined;
  const stop = (e: MouseEvent) => e.stopPropagation();
  const info = (e: MouseEvent) => {
    e.stopPropagation();
    onInfo(app);
  };

  if (app.tier === "roadmap") {
    return (
      <div className="carto-card plan" style={style} onClick={() => onInfo(app)}>
        <div className="carto-hd">
          <b>{app.name}</b>
          <span className="carto-tag">PLANNED</span>
        </div>
        <div className="carto-btns">
          <button className="carto-btn info" onClick={info}>
            Info
          </button>
        </div>
      </div>
    );
  }

  const openLabel = app.tier === "public" ? "Open" : "Sign in";
  const open = () =>
    app.url && window.open(app.url, "_blank", "noopener,noreferrer");
  return (
    <div className="carto-card live" style={style} onClick={open}>
      <div className="carto-thumb" style={{ height: app.tier === "public" ? 190 : 152 }}>
        {app.thumb ? <img src={THUMB(app.thumb)} alt="" /> : null}
      </div>
      <div className="carto-foot">
        <div className="carto-hd">
          <span className={`carto-dot ${app.status === "down" ? "down" : ""}`} />
          <b>{app.name}</b>
          <span className="carto-sub">{app.sub}</span>
        </div>
        {app.login && (
          <div className="carto-auth">
            {SHIELD}
            <span>employee sign-in required · see Info</span>
          </div>
        )}
        <div className="carto-btns">
          <a
            className="carto-btn open"
            href={app.url}
            target="_blank"
            rel="noreferrer"
            onClick={stop}
          >
            {openLabel} ↗
          </a>
          <button className="carto-btn info" onClick={info}>
            Info
          </button>
        </div>
      </div>
    </div>
  );
}

// Simplified phone layout: region titles + cards stacked vertically, no flows.
const GROUPS = [
  { tier: "public", title: "PUBLIC-FACING · no sign-in", shield: false, note: "" },
  { tier: "enterprise", title: "ENTERPRISE · sign-in required", shield: true, note: ENTERPRISE_NOTE },
  { tier: "roadmap", title: "ON THE HORIZON · roadmap", shield: false, note: "" },
] as const;

function MobileList({
  apps,
  onInfo,
}: {
  apps: CartoApp[];
  onInfo: (a: CartoApp) => void;
}) {
  return (
    <div className="carto-list">
      {GROUPS.map((g) => {
        const items = apps.filter((a) => a.tier === g.tier);
        if (!items.length) return null;
        return (
          <section key={g.tier} className="carto-group">
            <div className="carto-region-m">
              {g.shield ? SHIELD : null} {g.title}
            </div>
            {g.note && <div className="carto-note-m">{g.note}</div>}
            <div className={g.tier === "roadmap" ? "carto-roadmap-m" : "carto-stack"}>
              {items.map((a) => (
                <AppCard key={a.id} app={a} onInfo={onInfo} chart={false} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function Cartography() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<CartoApp | null>(null);
  const narrow = useNarrow();

  useEffect(() => {
    let alive = true;
    const load = () =>
      getCartography()
        .then((d) => {
          if (alive) {
            setData(d);
            setError(null);
          }
        })
        .catch((e: unknown) => {
          if (alive) setError(String(e));
        });
    load();
    const id = setInterval(load, 30_000); // refresh health
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <Stack direction="column" gap="lg">
      <Stack direction="column" gap="2xs">
        <Text variant="overline" color="brand">
          ARCHIPEL LABS · SIMULATOR
        </Text>
        <Text variant="h2" as="h1">
          The chart
        </Text>
        <Text variant="body" color="muted">
          the company's applications by tier: the public storefront, the enterprise
          tools behind sign-in, and what's on the roadmap.
        </Text>
      </Stack>

      {error && !data ? (
        <Text color="danger">Couldn’t load the chart. Is the backend up? ({error})</Text>
      ) : !data ? (
        <Text color="muted">Loading…</Text>
      ) : narrow ? (
        <MobileList apps={data.apps} onInfo={setInfo} />
      ) : (
        <div className="carto-scroll">
          <div className="carto-stage">
            <div className="carto-region" style={{ top: 8 }}>
              PUBLIC-FACING · no sign-in
            </div>
            <div className="carto-sep" style={{ top: 380 }} />
            <div className="carto-region" style={{ top: 400 }}>
              {SHIELD} ENTERPRISE · sign-in required
            </div>
            <div className="carto-note" style={{ top: 422 }}>
              {ENTERPRISE_NOTE}
            </div>
            <div className="carto-sep" style={{ top: 782 }} />
            <div className="carto-region" style={{ top: 802 }}>
              ON THE HORIZON · roadmap
            </div>

            <svg className="carto-flows" width="1010" height="1000">
              <defs>
                <marker id="carto-mg" markerWidth="11" markerHeight="10" refX="8" refY="4.5" orient="auto">
                  <path d="M0,0 L9,4.5 L0,9 Z" fill="var(--green-700)" />
                </marker>
                <marker id="carto-mp" markerWidth="10" markerHeight="9" refX="7" refY="4" orient="auto">
                  <path d="M0,0 L8,4 L0,8 Z" fill="var(--slate-400)" />
                </marker>
              </defs>
              {data.flows.map((f) => (
                <Flow key={`${f.from}-${f.to}`} flow={f} />
              ))}
            </svg>

            {data.apps.map((a) => (
              <AppCard key={a.id} app={a} onInfo={setInfo} />
            ))}

            <div className="carto-roadmap-arc" style={{ top: 1058 }}>
              SUPPLIERS → INVENTORY → ACCOUNTING → POS → STORES → OMNICHANNEL
            </div>
          </div>
        </div>
      )}

      {info && (
        <div className="carto-drawer">
          <button className="close" onClick={() => setInfo(null)}>
            ✕
          </button>
          <Stack direction="column" gap="sm">
            <Text variant="overline" color="muted">
              {info.tier}
              {info.status !== "planned" ? ` · ${info.status}` : ""}
            </Text>
            <Text variant="h3" as="h2">
              {info.name}
            </Text>
            {info.sub && (
              <Text variant="small" color="muted">
                {info.sub}
              </Text>
            )}
            {info.blurb && <Text variant="body">{info.blurb}</Text>}
            {info.login && (
              <div className="carto-cred-box">
                <div className="carto-cred-head">
                  {SHIELD} DEMO SIGN&#8209;IN · EMPLOYEE ACCESS
                </div>
                <div className="carto-cred-row">
                  <span className="carto-cred-label">User</span>
                  <code className="carto-cred-val">{info.login.user}</code>
                  <CopyBtn text={info.login.user} />
                </div>
                <div className="carto-cred-row">
                  <span className="carto-cred-label">Pass</span>
                  <code className="carto-cred-val">{info.login.password}</code>
                  <CopyBtn text={info.login.password} />
                </div>
              </div>
            )}
            {info.url && (
              <a className="carto-btn open" href={info.url} target="_blank" rel="noreferrer">
                {info.tier === "public" ? "Open" : "Sign in"} ↗
              </a>
            )}
          </Stack>
        </div>
      )}
    </Stack>
  );
}
