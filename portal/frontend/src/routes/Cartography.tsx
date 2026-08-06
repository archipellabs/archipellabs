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
  "no credentials are published yet · each card’s Info says which read-only account is still to be provisioned";

const MASTER_DATA_NOTE =
  "where reference data comes from, before the shop has it · the PIM joins this row when it ships";

// The collector is fed by *every* service above it, which is a relation this
// chart cannot draw without picking one and implying it is the only one. So it
// is said here instead of drawn as an arrow that would be wrong.
const MONITORING_NOTE =
  "the collector reads every service above · a grey light is a component this portal cannot ask, not one that is down";

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
  // storefront + the enterprise pair are shifted 150px left of their hand-tuned
  // originals (460/320/700) so the prominent cluster centers in the 1010 stage
  // instead of leaning right. The two storefront→enterprise paths below move with
  // them by the same 150 so the arrow geometry is unchanged.
  storefront: { x: 310, y: 40, w: 320 },
  backoffice: { x: 170, y: 460, w: 290 },
  analytics: { x: 550, y: 460, w: 290 },
  // Two platform bands, each a plain row of 92px cards (the height is fixed in
  // the stylesheet, and the lanes below are anchored to it). A row per concern
  // rather than one band with a fan: the fan overlapped its own boxes, and
  // "where master data comes from" and "how the company is watched" are two
  // questions that happen to share a floor.
  //
  // Nothing starts left of x=150: that corridor carries the roadmap's lane up to
  // the enterprise band, and a card in it would sit under the arrow.
  erp: { x: 150, y: 842, w: 150 },
  integration: { x: 340, y: 842, w: 150 },
  collector: { x: 150, y: 1046, w: 150 },
  logs: { x: 340, y: 1046, w: 150 },
  metrics: { x: 530, y: 1046, w: 150 },
  dashboards: { x: 720, y: 1046, w: 150 },
  // roadmap wraps onto two rows: 4 up top, 2 below (the ERP left this band when
  // it stopped being planned — it is a file drop now, one floor up).
  pim: { x: 110, y: 1248, w: 150 },
  inventory: { x: 300, y: 1248, w: 150 },
  accounting: { x: 490, y: 1248, w: 150 },
  suppliers: { x: 680, y: 1248, w: 150 },
  pos: { x: 110, y: 1356, w: 150 },
  stores: { x: 300, y: 1356, w: 150 },
};

// Hand-routed sea-lanes + label anchors (keyed "from-to").
const PATHS: Record<string, { d: string; lx: number; ly: number }> = {
  "storefront-analytics": { d: "M550,325 C 602,385 662,425 695,456", lx: 612, ly: 362 },
  "storefront-backoffice": { d: "M390,325 C 350,385 320,425 315,456", lx: 238, ly: 362 },
  // The master-data lane. `integration-backoffice` is the path this lab's first
  // incident travels: a row leaves the drop, the reconciliation deletes its
  // counterpart, and the shop quietly stops offering something.
  // Anchored to a card height fixed at 92px: the master-data row (y=842) centres
  // on 888, the monitoring row (y=1046) on 1092.
  //
  // Labels here are short by necessity — the gap between two cards is 40px and a
  // longer word draws straight across both. What each lane carries is in the
  // cards' own Info, which is where a sentence fits.
  "erp-integration": { d: "M302,888 L336,888", lx: 304, ly: 880 },
  "integration-backoffice": { d: "M415,838 C 405,796 360,752 322,720", lx: 402, ly: 778 },
  // The monitoring row. Two lanes are adjacent and drawn straight; the two that
  // would have to hop a card arc underneath at different depths, so they nest
  // instead of crossing.
  "collector-logs": { d: "M302,1092 L336,1092", lx: 0, ly: 0 },
  "metrics-dashboards": { d: "M682,1092 L716,1092", lx: 0, ly: 0 },
  "collector-metrics": { d: "M280,1140 C 340,1176 470,1176 532,1144", lx: 0, ly: 0 },
  "logs-dashboards": { d: "M470,1140 C 540,1194 660,1194 736,1146", lx: 0, ly: 0 },
  // Up the left corridor, clearing both platform bands.
  "pim-backoffice": { d: "M185,1244 C 112,1150 88,980 104,872 C 118,796 232,730 308,718", lx: 30, ly: 1124 },
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

  // The platform has no storefront and mostly no screen, so its card is the
  // live one with the picture taken out rather than a thumbnail-shaped hole:
  // a name, what it is, whether it answered, and the Info that carries the rest.
  if (app.tier === "platform") {
    return (
      <div className="carto-card platform" style={style} onClick={() => onInfo(app)}>
        <div className="carto-hd">
          <span className={`carto-dot ${app.status === "down" || app.status === "unknown" ? app.status : ""}`} />
          <b>{app.name}</b>
        </div>
        <div className="carto-sub">{app.sub}</div>
        {/* A platform component with a screen of its own gets the way in, like
            any other card. At the shared button size the pair overflowed 150px
            and wrapped — the stylesheet shrinks them for this variant rather
            than hiding the link, which is the thing worth keeping. */}
        <div className="carto-btns">
          {app.url && (
            <a
              className="carto-btn open"
              href={app.url}
              target="_blank"
              rel="noreferrer"
              onClick={stop}
            >
              Sign in ↗
            </a>
          )}
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
          <span className={`carto-dot ${app.status === "down" || app.status === "unknown" ? app.status : ""}`} />
          <b>{app.name}</b>
          <span className="carto-sub">{app.sub}</span>
        </div>
        {/* On the tier, not on `login`: these cards need a sign-in whether or
            not this portal has a credential to offer for them, and hanging the
            notice on the credential made it vanish the moment the placeholder
            ones were removed. */}
        {app.tier === "enterprise" && (
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
  { tier: "platform", title: "PLATFORM · master data & monitoring", shield: false, note: MONITORING_NOTE },
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
          the company's applications and the platform under them: the public storefront,
          the enterprise tools behind sign-in, where its reference data comes from,
          how it is watched, and what's on the roadmap.
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
            <div className="carto-region" style={{ top: 798 }}>
              PRODUCT INFORMATION · systems of record
            </div>
            <div className="carto-note" style={{ top: 820 }}>
              {MASTER_DATA_NOTE}
            </div>
            <div className="carto-sep" style={{ top: 964 }} />
            <div className="carto-region" style={{ top: 980 }}>
              MONITORING · logs &amp; metrics
            </div>
            <div className="carto-note" style={{ top: 1002 }}>
              {MONITORING_NOTE}
            </div>
            <div className="carto-sep" style={{ top: 1200 }} />
            <div className="carto-region" style={{ top: 1216 }}>
              ON THE HORIZON · roadmap
            </div>

            <svg className="carto-flows" width="1010" height="1300">
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

            <div className="carto-roadmap-arc" style={{ top: 1470 }}>
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
            {info.todo && (
              <div className="carto-todo">
                <span className="carto-todo-tag">TO DO</span>
                <span>{info.todo}</span>
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
