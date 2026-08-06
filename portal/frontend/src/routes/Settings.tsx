import { useCallback, useEffect, useState } from "react";
import {
  applySetting,
  getSettings,
  type FlowState,
  type SettingValue,
  type SimulatorSettings,
} from "../api";
import { Guard } from "../components/Guard";
import { Badge, Text } from "../ui";
import "./settings.css";

/** Where a value came from, said in words rather than in jargon.
 *
 *  The distinction is the whole point of the reset button: clearing an override
 *  lands on a deployment's choice or on the shipped value, and those are
 *  different promises. */
const SOURCE: Record<SettingValue["source"], { tone: "brand" | "info" | "neutral"; what: string }> = {
  database: { tone: "brand", what: "set here" },
  environment: { tone: "info", what: "set by this deployment" },
  default: { tone: "neutral", what: "shipped default" },
};

/** What each knob does, in the operator's terms.
 *
 *  Kept here rather than asked of the simulator: `describe` returns values and
 *  layers, which is a contract worth keeping narrow. A sentence for a human is
 *  presentation, and presentation belongs to the thing presenting. A key with no
 *  entry still renders — it simply arrives without a gloss, which is the right
 *  failure for a knob added upstream before this page hears about it. */
const ABOUT: Record<string, string> = {
  base_arrivals_per_minute: "How many customers arrive per minute, before the market mix splits them.",
  market_mix: "How arrivals divide between markets. Weights, not percentages — they are normalised.",
  max_arrivals_per_tick: "A ceiling per tick, so a burst cannot outrun the browser pool.",
  fast: "Skip the human pauses in a customer journey. Read per run, so it applies to the next customer.",
};

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

function isWeights(value: unknown): value is Record<string, number> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.values(value).every(isNumber)
  );
}

/** One row: what it reads, an editor for its shape, and the two verbs.
 *
 *  The editor is chosen from the *value's* shape rather than from a table of
 *  key names, so a knob added upstream gets a working control without this file
 *  being edited — and a knob whose shape nothing here recognises says so
 *  instead of rendering a text box that would post the wrong type. */
function Knob({
  name,
  setting,
  onChange,
}: {
  name: string;
  setting: SettingValue;
  onChange: (key: string, value: unknown) => Promise<void>;
}) {
  const [draft, setDraft] = useState<unknown>(setting.value);
  const [busy, setBusy] = useState(false);

  // The server's value wins whenever it changes — after an apply, a reset, or a
  // reload. Without this the row would keep showing what was typed even when
  // the simulator coerced or rejected it.
  useEffect(() => setDraft(setting.value), [setting.value]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(setting.value);
  const overridden = setting.source === "database";
  const source = SOURCE[setting.source];

  const send = async (value: unknown) => {
    setBusy(true);
    try {
      await onChange(name, value);
    } finally {
      setBusy(false);
    }
  };

  let editor;
  if (typeof setting.value === "boolean") {
    editor = (
      <label className="settings-switch">
        <input
          type="checkbox"
          checked={draft === true}
          disabled={busy}
          onChange={(event) => void send(event.target.checked)}
        />
        <span>{draft === true ? "on" : "off"}</span>
      </label>
    );
  } else if (isNumber(setting.value)) {
    editor = (
      <input
        type="number"
        className="settings-input"
        value={isNumber(draft) ? draft : ""}
        min={0}
        step="any"
        disabled={busy}
        onChange={(event) => setDraft(event.target.valueAsNumber)}
        aria-label={name}
      />
    );
  } else if (isWeights(setting.value)) {
    const weights = isWeights(draft) ? draft : {};
    editor = (
      <div className="settings-weights">
        {Object.entries(weights).map(([market, weight]) => (
          <label key={market} className="settings-weight">
            <span className="settings-weight__name">{market}</span>
            <input
              type="number"
              className="settings-input settings-input--narrow"
              value={weight}
              min={0}
              step="any"
              disabled={busy}
              onChange={(event) =>
                setDraft({ ...weights, [market]: event.target.valueAsNumber })
              }
            />
          </label>
        ))}
      </div>
    );
  } else {
    editor = (
      <Text variant="small" color="muted">
        no editor for this shape — <code>{JSON.stringify(setting.value)}</code>
      </Text>
    );
  }

  return (
    <div className="settings-knob">
      <div className="settings-knob__head">
        <code className="settings-knob__name">{name}</code>
        <Badge appearance="soft" tone={source.tone} size="sm">
          {source.what}
        </Badge>
      </div>
      {ABOUT[name] && (
        <Text variant="small" color="muted">
          {ABOUT[name]}
        </Text>
      )}
      <div className="settings-knob__row">
        {editor}
        {/* Booleans apply on toggle — a checkbox with an Apply button beside it
            invites the reading that the box alone did something. */}
        {typeof setting.value !== "boolean" && (
          <button
            type="button"
            className="settings-apply"
            disabled={!dirty || busy}
            onClick={() => void send(draft)}
          >
            Apply
          </button>
        )}
        {overridden && (
          <button
            type="button"
            className="settings-reset"
            disabled={busy}
            onClick={() => void send(null)}
            title={`Back to ${JSON.stringify(setting.static)}`}
          >
            Reset
          </button>
        )}
      </div>
    </div>
  );
}

function Flow({
  name,
  flow,
  onChange,
}: {
  name: string;
  flow: FlowState;
  onChange: (key: string, value: unknown) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="settings-flow">
      <div className="settings-flow__head">
        <code className="settings-knob__name">{name}</code>
        {!flow.mounted && (
          <Badge appearance="soft" tone="neutral" size="sm">
            not wired in
          </Badge>
        )}
      </div>
      <Text variant="small" color="muted">
        {flow.what}
      </Text>
      <label className="settings-switch">
        <input
          type="checkbox"
          checked={flow.running}
          // A flow that was never constructed cannot be switched on from here:
          // `include(enabled=)` decided that at boot and only a restart revisits
          // it. Offering the toggle would promise something the switch cannot do.
          disabled={busy || !flow.mounted}
          onChange={async (event) => {
            setBusy(true);
            try {
              await onChange(name, event.target.checked);
            } finally {
              setBusy(false);
            }
          }}
        />
        <span>{flow.mounted ? (flow.running ? "running" : "paused") : "unavailable"}</span>
      </label>
    </div>
  );
}

function Console() {
  const [settings, setSettings] = useState<SimulatorSettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    getSettings()
      .then((next) => {
        setSettings(next);
        setError(null);
      })
      .catch((failure) => setError(failure instanceof Error ? failure.message : String(failure)));
  }, []);

  useEffect(load, [load]);

  // Re-reading after every change rather than patching the row in place: the
  // simulator coerces values on the way in and answers with the layer that now
  // applies, so what it reports back is the truth and the local guess is not.
  const change = useCallback(
    async (key: string, value: unknown) => {
      try {
        await applySetting(key, value);
        setError(null);
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : String(failure));
      }
      load();
    },
    [load],
  );

  if (error && settings === null) {
    return (
      <section className="settings">
        <Text variant="h2">Simulator settings</Text>
        <Text color="danger">{error}</Text>
        <Text variant="small" color="muted">
          These come from the simulator over the bus, so this fails when the simulator is
          not running — not when the portal is broken.
        </Text>
      </section>
    );
  }

  if (settings === null) return <section className="settings">Loading…</section>;

  return (
    <section className="settings">
      <header className="settings-intro">
        <Text variant="h2">Simulator settings</Text>
        <Text color="muted">
          Changes apply to the running simulator within about a minute — it reads from a
          snapshot rather than the database on every tick. Nothing here restarts anything.
        </Text>
      </header>

      {error && <Text color="danger">{error}</Text>}

      <Text variant="overline">Values</Text>
      <div className="settings-grid">
        {Object.entries(settings.values).map(([name, setting]) => (
          <Knob key={name} name={name} setting={setting} onChange={change} />
        ))}
      </div>

      <Text variant="overline">Flows</Text>
      <Text variant="small" color="muted">
        Pausing a flow stops it doing new work; it does not unbuild it. A flow that was not
        wired in at boot cannot be started from here.
      </Text>
      <div className="settings-grid">
        {Object.entries(settings.flows).map(([name, flow]) => (
          <Flow key={name} name={name} flow={flow} onChange={change} />
        ))}
      </div>
    </section>
  );
}

export function Settings() {
  return (
    <Guard title="Settings">
      <Console />
    </Guard>
  );
}
