export interface OutcomeCounts {
  completed: number;
  abandoned: number;
  errored: number;
  other: number;
}

export interface Bucket {
  key: string;
  count: number;
}

export interface HourCount {
  hour: string;
  count: number;
}

export interface TimeWindow {
  last_24h: number;
  last_1h: number;
}

export interface Analytics {
  window: TimeWindow;
  outcome: OutcomeCounts;
  by_journey: Bucket[];
  by_device: Bucket[];
  by_hour: HourCount[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`API ${res.status}`);
  return (await res.json()) as T;
}

/** `platform` is what carries the data and what watches the company — no
 *  storefront, mostly no screen. It is on the chart because an incident lives
 *  there as often as it lives in an application. */
export type Tier = "public" | "enterprise" | "platform" | "roadmap";
/** `unknown` is live-but-unconfirmable: a component this portal has no way to
 *  ask. Distinct from `down` on purpose — a red light on a healthy service sends
 *  somebody to look at the one thing that has nothing wrong with it. */
export type Status = "up" | "down" | "unknown" | "planned";

export interface CartoApp {
  id: string;
  name: string;
  sub?: string;
  tier: Tier;
  url?: string;
  thumb?: string;
  login?: { user: string; password: string };
  /** What is still missing about getting in. Shown as a to-do rather than as a
   *  credential: the cards used to carry `<TODO>` in the user and password
   *  fields, complete with a copy button, so the one thing a visitor could take
   *  away from them was the literal string `<TODO>`. */
  todo?: string;
  blurb?: string;
  status: Status;
}

export interface CartoFlow {
  from: string;
  to: string;
  label: string;
  kind: "live" | "planned";
  bidir?: boolean;
}

export interface Cartography {
  apps: CartoApp[];
  flows: CartoFlow[];
}

export const getAnalytics = () => get<Analytics>("/api/analytics");
export const getCartography = () => get<Cartography>("/api/cartography");

/* --- The door ------------------------------------------------------------- */

/** `configured` is separate from `signed_in` so the page can tell a visitor who
 *  needs to sign in from a deployment that set no password and therefore closed
 *  these pages to everyone. One is a prompt; the other is an operator's problem
 *  that would be invisible if both read "please sign in". */
export interface SessionState {
  signed_in: boolean;
  configured: boolean;
}

/** The message a failed request carries, or a fallback naming the status.
 *
 *  FastAPI puts it in `detail`; the simulator's own refusals travel there too,
 *  and they name the keys it accepts — which is exactly what somebody who
 *  mistyped one needs to read. */
async function reason(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* not JSON — fall through to the status */
  }
  return `request failed (${res.status})`;
}

export const getSession = () => get<SessionState>("/api/session");

export async function login(password: string): Promise<SessionState> {
  const res = await fetch("/api/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!res.ok) throw new Error(await reason(res));
  return (await res.json()) as SessionState;
}

export async function logout(): Promise<SessionState> {
  const res = await fetch("/api/logout", { method: "POST" });
  if (!res.ok) throw new Error(await reason(res));
  return (await res.json()) as SessionState;
}

/* --- Simulator settings --------------------------------------------------- */

/** One knob: what it reads now, and which layer supplied that.
 *
 *  `static` is what clearing an override would restore and `default` is what
 *  ships in the code. They differ exactly when this deployment set the key, and
 *  both are needed to say honestly what a reset does — "back to 3/min" reads
 *  very differently from "back to whatever this deployment configured". */
export interface SettingValue {
  value: unknown;
  source: "database" | "environment" | "default";
  static: unknown;
  default: unknown;
}

/** A flow of the simulated company. `mounted` is the static wiring decision —
 *  whether the flow was constructed at boot, which no runtime switch can undo —
 *  and `running` is meaningful only when mounted. */
export interface FlowState {
  mounted: boolean;
  running: boolean;
  what: string;
}

export interface SimulatorSettings {
  values: Record<string, SettingValue>;
  flows: Record<string, FlowState>;
}

export async function getSettings(): Promise<SimulatorSettings> {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error(await reason(res));
  return (await res.json()) as SimulatorSettings;
}

/** Change one knob. **`null` means reset** — drop the override and fall back to
 *  the layer below. The simulator's own sentinel, passed through rather than
 *  translated: a second vocabulary for one idea is how two ends stop agreeing. */
export async function applySetting(key: string, value: unknown): Promise<void> {
  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, value }),
  });
  if (!res.ok) throw new Error(await reason(res));
}

/* --- Ask an analyst ------------------------------------------------------- */

/** The step vocabulary the agents emit: `agent_core.harness.Kind`, closed on
 *  purpose so nothing here changes when a loop is swapped.
 *
 *  It is NOT the CLI watcher's glyph set, which an earlier version of this file
 *  took it for — those are display marks with words of their own, and reading
 *  them off the terminal instead of the wire made every step but one arrive as
 *  `other`. */
export type AskStepKind =
  | "started"
  | "thinking"
  | "command"
  | "output"
  | "message"
  | "tool"
  | "finished"
  | "error"
  | "other";

/** The answer's keys vary by agent (detected/summary, diagnosis, root_cause,
 *  remediation, confidence, findings), so the shape stays open and the page
 *  renders whatever fields arrive. */
export type AskAnswer = Record<string, unknown>;

export interface AskFinding {
  fact: string;
  source: string;
}

/** What a run consumed, as `bus.spent` reports it beside the verdict.
 *
 *  Every field is optional because the envelope only carries what the loop
 *  actually measured, and a missing counter is not a zero.
 *
 *  Four of these numbers are traps if rendered as a flat row:
 *  - `cost` and `estimated_cost` are **different claims and must not look
 *    alike**. The first is what a loop reports it was billed — a receipt, and
 *    only opencode sends one. The second is tokens multiplied by a rate
 *    somebody transcribed into `model-prices.json` on a date, computed backend
 *    side and sent only when no receipt exists. Shown as though it were a
 *    receipt it would tell a reader something this repository does not know.
 *  - Neither is ever invented here. A model nobody has priced yields *both*
 *    absent, which is the common case — and unpriced is not `$0.00`, not a
 *    dash, not "free". It is token counts and no money.
 *  - `cache_read_tokens` is a *subset* of `input_tokens`, not an addition.
 *  - `reasoning_tokens` is billed and invisible *inside* `output_tokens`.
 */
export interface AskSpent {
  run_id?: string;
  harness?: string;
  model?: string;
  effort?: string;
  duration_ms?: number;
  tool_calls?: number;
  model_requests?: number;
  input_tokens?: number;
  output_tokens?: number;
  reasoning_tokens?: number;
  cache_read_tokens?: number;
  /** What the loop says it was billed. A receipt. */
  cost?: number;
  /** What the published rate says it would come to. Arithmetic. */
  estimated_cost?: number;
}

export type AskEvent =
  | { kind: "started" }
  /** `n` is the analyst's own 1-based counter, and it is the ONLY ordering
   *  there is. Steps are published fire-and-forget so that narrating never
   *  slows an investigation, which means two of them can be in flight at once
   *  and land out of order — observed: a run's last command arriving after its
   *  `finished`. Render by `n`, never by arrival.
   *
   *  `text` and `command` are clipped to `STEP_TEXT_CLIP` before they are
   *  published — an event is a window on a step, not a copy of it — so a long
   *  one arrives truncated and the page has to say so. */
  | {
      kind: "step";
      n?: number;
      step: AskStepKind;
      text?: string;
      tool?: string;
      command?: string;
      /** Set when the command opened a skill, e.g. `"shop-webservice"`. Inferred
       *  agent-side from the `.agents/skills/` path, because no loop reports
       *  opening a skill as anything but the command that read the file. */
      skill?: string;
      duration_ms?: number;
      args?: Record<string, unknown>;
    }
  | { kind: "answered"; answer: AskAnswer; spent?: AskSpent }
  | { kind: "failed"; reason: string; spent?: AskSpent };

/** Where `agent_core.run.MAX_TEXT` cuts a step's text for the bus.
 *
 *  Kept here so the page can mark a step as clipped rather than present a
 *  truncation as the whole output. A step that arrives at exactly this length
 *  was almost certainly cut; the full text is in the run record. */
export const STEP_TEXT_CLIP = 400;

export interface AskRequest {
  agent: string;
  model: string;
  effort: string;
  question: string;
}

/** A 409 ("that analyst is already busy") is an expected reply, not a failure,
 *  so the result comes back as data instead of a thrown error. */
export type AskStart =
  | { ok: true; reference: string }
  | { ok: false; busy: boolean; detail: string };

const str = (v: unknown) => (typeof v === "string" ? v : undefined);
const num = (v: unknown) =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;
const dict = (v: unknown) =>
  typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : undefined;

const STEP_KINDS: readonly AskStepKind[] = [
  "started",
  "thinking",
  "command",
  "output",
  "message",
  "tool",
  "finished",
  "error",
  "other",
];

/** Who can be asked, from the backend rather than from a copy kept here.
 *
 *  The page held its own list of four while the bus served seven, so three
 *  employees existed and were unreachable — and the endpoint written so the page
 *  "never offers a door that is not there" was never called. A hardcoded roster
 *  fails in both directions: it hides a hire, and it offers a name nobody
 *  serves. */
export async function fetchAgents(): Promise<string[]> {
  const { agents } = await get<{ agents: string[] }>("/api/agents");
  return agents;
}

export async function startAsk(body: AskRequest): Promise<AskStart> {
  let res: Response;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e: unknown) {
    return { ok: false, busy: false, detail: `Couldn’t reach the backend (${e})` };
  }
  let payload: unknown = null;
  try {
    payload = await res.json();
  } catch {
    // an empty or non-JSON body; the status still carries the meaning
  }
  const detail = str((payload as { detail?: unknown } | null)?.detail);
  if (res.status === 409) {
    return { ok: false, busy: true, detail: detail ?? "That analyst is already busy." };
  }
  if (!res.ok) {
    return { ok: false, busy: false, detail: detail ?? `API ${res.status}` };
  }
  const reference = str((payload as { reference?: unknown } | null)?.reference);
  if (!reference) {
    return {
      ok: false,
      busy: false,
      detail: "The question was accepted but no reference came back.",
    };
  }
  return { ok: true, reference };
}

export const askEventsUrl = (reference: string) =>
  `/api/ask/${encodeURIComponent(reference)}/events`;

/** The run's accounting, read field by field.
 *
 *  Nothing is defaulted to zero. A counter the loop never measured and a counter
 *  that measured nothing are different facts, and only one of them is worth
 *  printing — so an absent field stays absent all the way to the page, which
 *  omits it rather than showing a confident `0`.
 */
function parseSpent(value: unknown): AskSpent | undefined {
  const o = dict(value);
  if (!o) return undefined;
  const spent: AskSpent = {
    run_id: str(o.run_id),
    harness: str(o.harness),
    model: str(o.model),
    effort: str(o.effort),
    duration_ms: num(o.duration_ms),
    tool_calls: num(o.tool_calls),
    model_requests: num(o.model_requests),
    input_tokens: num(o.input_tokens),
    output_tokens: num(o.output_tokens),
    reasoning_tokens: num(o.reasoning_tokens),
    cache_read_tokens: num(o.cache_read_tokens),
    cost: num(o.cost),
    estimated_cost: num(o.estimated_cost),
  };
  return Object.values(spent).some((v) => v !== undefined) ? spent : undefined;
}

/** Parse one SSE payload. Anything unrecognised is dropped rather than thrown —
 *  a stray frame must not take the run down. */
export function parseAskEvent(raw: string): AskEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null) return null;
  const o = data as Record<string, unknown>;
  switch (o.kind) {
    case "started":
      return { kind: "started" };
    case "step": {
      const step = STEP_KINDS.includes(o.step as AskStepKind)
        ? (o.step as AskStepKind)
        : "other";
      return {
        kind: "step",
        n: num(o.n),
        step,
        text: str(o.text),
        tool: str(o.tool),
        command: str(o.command),
        skill: str(o.skill),
        duration_ms: num(o.duration_ms),
        args: dict(o.args),
      };
    }
    case "answered":
      return {
        kind: "answered",
        answer: (dict(o.answer) as AskAnswer | undefined) ?? {},
        spent: parseSpent(o.spent),
      };
    case "failed":
      return {
        kind: "failed",
        reason: str(o.reason) ?? "The run failed.",
        spent: parseSpent(o.spent),
      };
    default:
      return null;
  }
}
