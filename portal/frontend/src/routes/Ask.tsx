import {
  type FormEvent,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Badge, Stack, Stat, Text } from "../ui";
import { Guard } from "../components/Guard";
import {
  askEventsUrl,
  fetchAgents,
  parseAskEvent,
  startAsk,
  STEP_TEXT_CLIP,
  type AskAnswer,
  type AskFinding,
  type AskSpent,
  type AskStepKind,
} from "../api";
import "./ask.css";

// The roster comes from the bus, not from here — see `fetchAgents`. This is
// only what the picker shows before that answer arrives, so a slow first paint
// is not an empty select.
const AGENTS_UNTIL_KNOWN = ["angel"];

const MODELS = [
  { value: "gpt-5.6-luna", label: "luna" },
  { value: "gpt-5.6-terra", label: "terra" },
  { value: "gpt-5.6-sol", label: "sol" },
] as const;

const EFFORTS = ["low", "medium", "high", "xhigh"] as const;

const PLACEHOLDER = "Are Canadian customers able to check out?";

/** The modifier the submit shortcut actually wants on this keyboard.
 *
 *  `onQuestionKey` accepts either meta or control, so the hint has to pick one
 *  to show. Printing both — the page said `⌘/Ctrl + Enter` — is a shortcut
 *  nobody's keyboard has, and it is the only place the page tells a reader the
 *  key exists at all. */
const MOD_KEY =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform)
    ? "⌘"
    : "Ctrl";

/** How long a run may say nothing before the page stops pretending it is fine.
 *
 *  Chosen against the failure it names rather than against a model's latency: an
 *  employee whose process is not running produces *exactly* this — a call that
 *  sits on the queue for its full fifteen-minute ttl with no error, no event and
 *  no way for a reader to tell it apart from thinking hard. A minute is longer
 *  than any observed first step and far short of the ttl, so the notice is a
 *  warning rather than a verdict, and the run is left alone to prove it wrong. */
const SILENCE_MS = 60_000;

// One glyph per step kind, keyed by the closed vocabulary the agents publish.
// The marks echo the CLI watcher's so a trace read here and a trace read in a
// terminal look like the same run — but the keys come from the wire, which is
// what the watcher's own word list could not be trusted for.
const GLYPH: Record<AskStepKind, string> = {
  started: "▸",
  thinking: "*",
  command: ">",
  output: "<",
  message: "”",
  tool: "+",
  finished: "▪",
  error: "!",
  other: "?",
};

/* --- run state ------------------------------------------------------------- */

type Phase =
  | "idle"
  | "starting" // the POST is in flight
  | "open" // the stream is connected, nothing has arrived yet
  | "running"
  | "answered"
  | "failed" // the agent reported a failure
  | "lost" // the stream dropped before an answer
  | "error"; // the POST itself didn't take

const LIVE: Phase[] = ["starting", "open", "running"];

const STATUS: Record<Phase, { label: string; tone: "neutral" | "brand" | "success" | "warning" | "danger" }> = {
  idle: { label: "idle", tone: "neutral" },
  starting: { label: "dispatching", tone: "neutral" },
  open: { label: "connected", tone: "brand" },
  running: { label: "working", tone: "brand" },
  answered: { label: "answered", tone: "success" },
  failed: { label: "failed", tone: "danger" },
  lost: { label: "connection lost", tone: "warning" },
  error: { label: "not started", tone: "danger" },
};

interface Run {
  agent: string;
  model: string;
  effort: string;
  question: string;
  reference: string;
}

interface TraceStep {
  /** The analyst's own 1-based counter when it sent one, else arrival order.
   *  Sorting on it is not cosmetic: steps are published fire-and-forget so
   *  narrating never slows an investigation, so two can be in flight at once
   *  and land out of order — a run's last command was observed arriving after
   *  its `finished`. Arrival order is not the order things happened. */
  id: number;
  kind: AskStepKind;
  text: string;
  tool?: string;
  command?: string;
  skill?: string;
  durationMs?: number;
  args?: Record<string, unknown>;
}

interface Group {
  key: number; // the first step's id — stable as the group grows
  kind: AskStepKind;
  steps: TraceStep[];
}

// Consecutive steps of one kind read as one move ("read × 4"), not four lines.
function groupSteps(steps: TraceStep[]): Group[] {
  const out: Group[] = [];
  for (const s of steps) {
    const last = out[out.length - 1];
    if (last && last.kind === s.kind) last.steps.push(s);
    else out.push({ key: s.id, kind: s.kind, steps: [s] });
  }
  return out;
}

const oneLine = (text: string) => text.replace(/\s+/g, " ").trim();

function formatElapsed(ms: number): { value: string; unit: string } {
  const s = ms / 1000;
  if (s < 60) return { value: s.toFixed(1), unit: "s" };
  const m = Math.floor(s / 60);
  return { value: `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`, unit: "min" };
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${String(Math.round(s % 60)).padStart(2, "0")}s`;
}

// Grouped with a narrow no-break space: `10 303` reads as one number at a glance
// where `10303` has to be counted, and the space can never wrap.
const GROUPED = new Intl.NumberFormat("en-US");
const count = (n: number) => GROUPED.format(n).replace(/,/g, " ");

/* --- reading a step -------------------------------------------------------- */

/** The `/bin/zsh -c "…"` every shell call arrives wrapped in.
 *
 *  The wrapper is the driver's, not the agent's: it is identical on every line
 *  and it pushes the half a reader cares about off the end of the row. Stripped
 *  for display only — the original stays on the step and an expanded command
 *  shows it verbatim, because what was executed is not always what was meant. */
const SHELL_WRAPPER = /^(?:[\w./-]*\/)?(?:sh|bash|zsh|dash|ksh)\s+-[a-z]*c\s+/;

function unwrapShell(command: string): { shown: string; wrapped: boolean } {
  const inner = command.replace(SHELL_WRAPPER, "");
  if (inner === command) return { shown: command.trim(), wrapped: false };
  const quote = inner[0];
  const quoted =
    (quote === '"' || quote === "'") && inner.length > 1 && inner.endsWith(quote);
  return { shown: (quoted ? inner.slice(1, -1) : inner).trim(), wrapped: true };
}

/** A step's text as pretty JSON, when it is JSON.
 *
 *  `message` is very often a draft of the verdict — a flat object of prose
 *  fields — and printed raw on one clipped line it is the least readable thing
 *  on the page. It also frequently does *not* parse, because the wire cuts at
 *  `STEP_TEXT_CLIP` and the cut lands mid-string; that is a truncation rather
 *  than malformed JSON, and the page says which. */
function asJson(text: string): string | null {
  if (!looksJson(text)) return null;
  try {
    return JSON.stringify(JSON.parse(text.trim()), null, 2) as string;
  } catch {
    return null;
  }
}

const looksJson = (text: string) => /^[[{]/.test(text.trim());

/** Whether the bus cut this text on the way here. An event is a window on a
 *  step, not a copy of it, and a window presented as the whole view is a lie a
 *  reader has no way to catch. */
const isClipped = (text: string) => text.length >= STEP_TEXT_CLIP;

const plural = (n: number, word: string) => `${count(n)} ${word}${n === 1 ? "" : "s"}`;

function sizeHint(text: string): string {
  const lines = text.split("\n").length;
  const chars = plural(text.length, "char");
  return lines > 1 ? `${plural(lines, "line")} · ${chars}` : chars;
}

/** One line standing in for a whole step, for a collapsed group's header. */
function summarise(step: TraceStep): string {
  if (step.skill) return `«${step.skill}»`;
  if (step.kind === "command") return unwrapShell(step.command || step.text).shown;
  if (step.kind === "tool") return step.tool || oneLine(step.text);
  return oneLine(step.text);
}

const CLIP_NOTE = `cut at ${count(STEP_TEXT_CLIP)} characters on the way here — the whole of it is in the run record`;

/* --- trace ----------------------------------------------------------------- */

/** How wide a command gets before it is worth folding rather than wrapping. */
const CMD_CLIP = 110;

const GROUP_WORD: Record<AskStepKind, string> = {
  started: "boundaries",
  thinking: "thoughts",
  command: "commands",
  output: "outputs",
  message: "messages",
  tool: "tool calls",
  finished: "boundaries",
  error: "errors",
  other: "steps",
};

function Glyph({ kind }: { kind: AskStepKind }) {
  return (
    <span className="ask-glyph" data-kind={kind} aria-hidden="true">
      {GLYPH[kind]}
    </span>
  );
}

const Duration = ({ ms }: { ms: number }) => (
  <span className="ask-dur">{formatDuration(ms)}</span>
);

const ClipNote = () => <p className="ask-clip">{CLIP_NOTE}</p>;

/** The one expander on the page, so every disclosure is a real button carrying a
 *  real `aria-expanded` and they all read the same. */
function More({
  open,
  onToggle,
  label,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <button type="button" className="ask-more" aria-expanded={open} onClick={onToggle}>
      <span className="ask-more__chev" aria-hidden="true">
        {open ? "▾" : "▸"}
      </span>
      {open ? "hide" : label}
    </button>
  );
}

/** `started` and `finished` are boundaries, not content: a rule with a word on
 *  it rather than a row pretending the run did something. */
function StepMark({ step }: { step: TraceStep }) {
  return (
    <div className="ask-mark" data-kind={step.kind}>
      <Glyph kind={step.kind} />
      <span className="ask-mark__label">
        {step.kind === "started" ? "the analyst began" : "the analyst stopped"}
      </span>
      <span className="ask-mark__rule" aria-hidden="true" />
    </div>
  );
}

function StepThinking({ step }: { step: TraceStep }) {
  return (
    <div className="ask-row" data-kind="thinking">
      <Glyph kind="thinking" />
      <div className="ask-row__main">
        <p className="ask-think">{step.text}</p>
        {isClipped(step.text) ? <ClipNote /> : null}
      </div>
    </div>
  );
}

function StepCommand({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const raw = step.command || step.text;
  const { shown, wrapped } = unwrapShell(raw);
  const foldable = wrapped || shown.length > CMD_CLIP || shown.includes("\n");
  return (
    <div className="ask-row" data-kind="command">
      <Glyph kind="command" />
      <div className="ask-row__main">
        <div className="ask-term" data-open={open}>
          <span className="ask-term__prompt" aria-hidden="true">
            $
          </span>
          <code className="ask-term__cmd">{shown}</code>
        </div>
        {foldable || step.durationMs !== undefined ? (
          <div className="ask-row__foot">
            {step.durationMs !== undefined ? <Duration ms={step.durationMs} /> : null}
            {foldable ? (
              <More open={open} onToggle={() => setOpen((v) => !v)} label="in full" />
            ) : null}
          </div>
        ) : null}
        {open && wrapped ? (
          <div className="ask-aside">
            <span className="ask-aside__label">as the loop ran it</span>
            <pre className="ask-pre">{raw}</pre>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** A skill is opened by a command that happens to read a `SKILL.md`, and no loop
 *  reports it as anything else. Rendered as the `sed` that did it, the move a
 *  reader would recognise — the analyst going to look something up — disappears
 *  into a line of shell. */
function StepSkill({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const raw = step.command || step.text;
  return (
    <div className="ask-row ask-row--tight" data-kind="command">
      <Glyph kind="command" />
      <div className="ask-row__main">
        <div className="ask-row__head">
          <span className="ask-row__label">opened</span>
          <code className="ask-chip ask-chip--skill">«{step.skill}»</code>
          <More open={open} onToggle={() => setOpen((v) => !v)} label="the command" />
        </div>
        {open ? <pre className="ask-pre">{unwrapShell(raw).shown}</pre> : null}
      </div>
    </div>
  );
}

function StepOutput({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const preview = oneLine(step.text);
  return (
    <div className="ask-row ask-row--tight" data-kind="output">
      <Glyph kind="output" />
      <div className="ask-row__main">
        <button
          type="button"
          className="ask-peek"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="ask-row__label">read</span>
          <span className="ask-peek__preview">{preview || "nothing came back"}</span>
          <span className="ask-peek__size">{sizeHint(step.text)}</span>
          <span className="ask-peek__chev" aria-hidden="true">
            {open ? "▾" : "▸"}
          </span>
        </button>
        {open ? <pre className="ask-pre ask-pre--tall">{step.text}</pre> : null}
        {isClipped(step.text) ? <ClipNote /> : null}
      </div>
    </div>
  );
}

/** The agent speaking, which on this stack is very often a draft of the verdict
 *  as a JSON object. Three cases, and telling them apart is the whole job:
 *  it parses and is laid out; it is a JSON *fragment* the wire cut mid-string,
 *  which is still code and is shown as code with the cut named; or it is prose,
 *  and gets the width and the line breaks prose needs. */
/** The sentences inside a verdict draft, in the order it wrote them.
 *
 *  An analyst speaking here is very often filling in the answer's fields, so
 *  the payload is an object whose values are the prose and whose keys are the
 *  contract. The prose is what a reader wants; the braces are what the wire
 *  needed. Nested values are left to the full view rather than flattened —
 *  `findings` is a list of objects and reads as noise inline. */
function saidIn(text: string): string | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text.trim());
  } catch {
    return null;
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return null;
  }
  // **The first field only** — `detected` on this contract, and whatever leads
  // on another. Reading every string value out was worse than the object it
  // replaced: `root_cause` and `remediation` on a mid-run draft are usually
  // "Not applicable.", twice, and `confidence` arrives as the bare word "high"
  // on a line of its own. A trace is a running commentary, and what an analyst
  // is *saying* at that moment is its opening line; the rest is the shape of an
  // answer it has not finished, and belongs with the object under "in full".
  const first = Object.values(parsed as Record<string, unknown>).find(
    (v): v is string => typeof v === "string" && v.trim().length > 0,
  );
  return first ? first.trim() : null;
}

function StepMessage({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const said = saidIn(step.text);
  const json = asJson(step.text);
  const fragment = json === null && looksJson(step.text);
  const cut = isClipped(step.text);
  return (
    <div className="ask-row" data-kind="message">
      <Glyph kind="message" />
      <div className="ask-row__main">
        {said ? (
          // **What it said, not how it was packaged.** A verdict draft used to
          // render as its whole pretty-printed object, so the one thing a
          // reader is following — the analyst's own sentences — arrived wearing
          // braces, quotes and field names. The object is still one click away,
          // because it is what the contract will be checked against.
          <>
            <p className="ask-say">{said}</p>
            <button
              type="button"
              className="ask-peek ask-peek--quiet"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              <span className="ask-row__label">in full</span>
              <span className="ask-peek__chev" aria-hidden="true">
                {open ? "▾" : "▸"}
              </span>
            </button>
            {open ? <pre className="ask-pre ask-pre--code">{json}</pre> : null}
          </>
        ) : fragment ? (
          <pre className="ask-pre ask-pre--code">{step.text}</pre>
        ) : (
          <p className="ask-say">{step.text}</p>
        )}
        {fragment ? (
          <p className="ask-clip">
            a draft of the answer, {CLIP_NOTE} — too short a fragment to lay out as JSON
          </p>
        ) : null}
        {cut && !fragment ? <ClipNote /> : null}
      </div>
    </div>
  );
}

/** A tool call's arguments, compactly. Values are stringified and capped: an
 *  argument is a label on the call here, not the call's payload. */
function argPairs(args: Record<string, unknown>): [string, string][] {
  return Object.entries(args).map(([k, v]) => {
    const shown = typeof v === "string" ? v : JSON.stringify(v);
    const text = shown ?? String(v);
    return [k, text.length > 48 ? `${text.slice(0, 48)}…` : text];
  });
}

function StepTool({ step }: { step: TraceStep }) {
  const pairs = step.args ? argPairs(step.args) : [];
  return (
    <div className="ask-row ask-row--tight" data-kind="tool">
      <Glyph kind="tool" />
      <div className="ask-row__main">
        <div className="ask-row__head">
          <span className="ask-row__label">called</span>
          <code className="ask-chip ask-chip--tool">{step.tool || "a tool"}</code>
          {pairs.length > 0 ? (
            <span className="ask-args">
              {pairs.map(([k, v]) => (
                <span key={k} className="ask-args__pair">
                  <span className="ask-args__key">{k}</span>=<span>{v}</span>
                </span>
              ))}
            </span>
          ) : null}
          {step.durationMs !== undefined ? <Duration ms={step.durationMs} /> : null}
        </div>
        {step.text ? <p className="ask-say">{step.text}</p> : null}
      </div>
    </div>
  );
}

function StepError({ step }: { step: TraceStep }) {
  return (
    <div className="ask-row ask-row--error" data-kind="error">
      <Glyph kind="error" />
      <div className="ask-row__main">
        <div className="ask-row__head">
          <span className="ask-row__label">error</span>
        </div>
        <pre className="ask-pre ask-pre--error">
          {step.text || "the loop reported a failure and said nothing more"}
        </pre>
      </div>
    </div>
  );
}

/** `other` is the vocabulary's escape hatch: a loop that grows a step type
 *  arrives here rather than being dropped, so it gets a row that shows whatever
 *  it carried. */
function StepPlain({ step }: { step: TraceStep }) {
  const [open, setOpen] = useState(false);
  const preview = oneLine(step.text);
  const long = preview.length > CMD_CLIP || step.text.includes("\n");
  return (
    <div className="ask-row ask-row--tight" data-kind={step.kind}>
      <Glyph kind={step.kind} />
      <div className="ask-row__main">
        <div className="ask-row__head">
          <span className="ask-row__label">{step.kind}</span>
          <span className="ask-plain">{preview}</span>
          {long ? (
            <More open={open} onToggle={() => setOpen((v) => !v)} label="in full" />
          ) : null}
        </div>
        {open ? <pre className="ask-pre">{step.text}</pre> : null}
      </div>
    </div>
  );
}

function StepItem({ step }: { step: TraceStep }) {
  switch (step.kind) {
    case "started":
    case "finished":
      return <StepMark step={step} />;
    case "thinking":
      return <StepThinking step={step} />;
    case "command":
      return step.skill ? <StepSkill step={step} /> : <StepCommand step={step} />;
    case "output":
      return <StepOutput step={step} />;
    case "message":
      return <StepMessage step={step} />;
    case "tool":
      return <StepTool step={step} />;
    case "error":
      return <StepError step={step} />;
    default:
      return <StepPlain step={step} />;
  }
}

function GroupRow({ group, live }: { group: Group; live: boolean }) {
  // `null` while nobody has touched it, so the default can follow the run.
  const [choice, setChoice] = useState<boolean | null>(null);
  if (group.steps.length === 1) return <StepItem step={group.steps[0]} />;

  // Folding is for *reading* a finished trace, not for hiding what is happening:
  // while the run is live the groups stay open, and they fold once it stops.
  // Folding only the group that is no longer newest was tried and is worse — a
  // block collapses out from under the reader every time the analyst changes
  // what it is doing. A reader who toggles one owns it from then on, live or not.
  const open = choice ?? live;
  const last = group.steps[group.steps.length - 1];
  return (
    <div className="ask-fold">
      <button
        type="button"
        className="ask-fold__head"
        aria-expanded={open}
        onClick={() => setChoice(!open)}
      >
        <Glyph kind={group.kind} />
        <span className="ask-fold__count">
          {group.steps.length} {GROUP_WORD[group.kind]}
        </span>
        <span className="ask-fold__preview">{open ? "" : summarise(last)}</span>
        <span className="ask-fold__chev" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
      </button>
      {open ? (
        <div className="ask-fold__body">
          {group.steps.map((s) => (
            <StepItem key={s.id} step={s} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Trace({
  steps,
  open,
  onToggle,
  elapsed,
  live,
}: {
  steps: TraceStep[];
  open: boolean;
  onToggle: () => void;
  elapsed: string;
  live: boolean;
}) {
  const groups = useMemo(() => groupSteps(steps), [steps]);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const [stick, setStick] = useState(true);
  const total = steps.length;

  // Follow the tail while it streams, unless the reader has scrolled up to look
  // at something.
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !stick || !open || total === 0) return;
    el.scrollTop = el.scrollHeight;
  }, [total, stick, open]);

  return (
    // `data-lead` while it streams: the trace is what the page is about between
    // the question being taken and the answer arriving, and the page's one lift
    // follows the subject rather than sitting on whichever block is topmost.
    <section className="ask-trace" data-lead={live ? "" : undefined}>
      <button type="button" className="ask-trace__head" aria-expanded={open} onClick={onToggle}>
        <span className="ask-trace__title">
          <span aria-hidden="true">{open ? "▾" : "▸"}</span> Trace
        </span>
        <span className="ask-trace__meta">
          {total} {total === 1 ? "step" : "steps"} · {elapsed}
        </span>
      </button>
      {open ? (
        <div
          className="ask-trace__body"
          ref={bodyRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 24);
          }}
        >
          {groups.length === 0 ? (
            <p className="ask-trace__empty">{live ? "waiting for the first step…" : "no steps"}</p>
          ) : (
            groups.map((g, i) => (
              <div
                key={g.key}
                className="ask-item"
                data-newest={live && i === groups.length - 1 ? "" : undefined}
              >
                <GroupRow group={g} live={live} />
              </div>
            ))
          )}
          {live && groups.length > 0 ? (
            <p className="ask-tail">
              <span className="ask-caret" aria-hidden="true" />
              still working
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

/* --- what the run consumed -------------------------------------------------- */

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 4,
});

function Meter({
  label,
  value,
  unit,
  of,
}: {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  of?: ReactNode;
}) {
  return (
    <div className="ask-spent__cell">
      <Stat label={label} value={value} unit={unit} />
      {of ? <span className="ask-spent__of">{of}</span> : null}
    </div>
  );
}

/** What the question cost, once the analyst has stopped.
 *
 *  Shown for a failure as well as an answer: a crash after twenty tool calls is
 *  precisely the run whose bill is worth seeing.
 *
 *  **The two money fields are not interchangeable and are not styled alike.**
 *  `cost` is what a loop reports it was billed; `estimated_cost` is tokens times
 *  a rate transcribed into the repository's own table, and it is marked as an
 *  estimate everywhere it appears. When neither arrives the run is unpriced —
 *  which is most runs — and the counters are shown with no money at all, because
 *  a `$0.00` or a dash in that slot reads as free.
 */
function Spent({ spent }: { spent: AskSpent }) {
  const spec = [spent.harness, spent.model, spent.effort].filter(Boolean).join(" · ");
  const priced = spent.cost ?? spent.estimated_cost;
  const measured = spent.cost !== undefined;
  return (
    <section className="ask-spent" aria-label="what the run consumed">
      <div className="ask-spent__head">
        <Text variant="overline" color="brand">
          What it took
        </Text>
        <span className="ask-spent__spec">
          {spec}
          {spent.run_id ? <span className="ask-spent__run"> · {spent.run_id}</span> : null}
        </span>
      </div>

      <div className="ask-spent__grid">
        {spent.duration_ms !== undefined ? (
          <Meter label="Took" value={formatDuration(spent.duration_ms)} />
        ) : null}
        {spent.tool_calls !== undefined ? (
          <Meter label="Tool calls" value={count(spent.tool_calls)} />
        ) : null}
        {spent.model_requests !== undefined ? (
          <Meter label="Model turns" value={count(spent.model_requests)} />
        ) : null}
        {spent.input_tokens !== undefined ? (
          <Meter
            label="Sent"
            value={count(spent.input_tokens)}
            unit="tokens"
            of={
              spent.cache_read_tokens !== undefined
                ? `of which ${count(spent.cache_read_tokens)} came from cache`
                : undefined
            }
          />
        ) : null}
        {spent.output_tokens !== undefined ? (
          <Meter
            label="Came back"
            value={count(spent.output_tokens)}
            unit="tokens"
            of={
              spent.reasoning_tokens !== undefined
                ? `of which ${count(spent.reasoning_tokens)} was reasoning`
                : undefined
            }
          />
        ) : null}
        {priced !== undefined ? (
          <div className="ask-spent__cell" data-money={measured ? "billed" : "estimated"}>
            <Stat
              label={measured ? "Billed" : "Estimated"}
              value={
                <span className="ask-money">
                  {measured ? null : (
                    <span className="ask-money__tilde" aria-hidden="true">
                      ~
                    </span>
                  )}
                  {USD.format(priced)}
                </span>
              }
            />
            <span className="ask-spent__of">
              {measured ? "reported by the loop" : "at the published rate"}
            </span>
          </div>
        ) : null}
      </div>

      <p className="ask-spent__note">
        {priced === undefined ? (
          <>
            No price: no loop reported one and nobody has written this model's rate down.
            Unpriced is not free — the counters above are what there is.
          </>
        ) : measured ? (
          <>
            A figure the loop reported it was billed. Cached tokens are part of what was
            sent, and reasoning tokens part of what came back — neither adds to the other.
          </>
        ) : (
          <>
            <strong>An estimate, not a receipt.</strong> No loop reported a bill, so this is
            the run's tokens at the rate written down in the repository's price table — the
            cached share priced as cached, not counted twice.
          </>
        )}
      </p>
    </section>
  );
}

/* --- answer ---------------------------------------------------------------- */

// The fields the analysts answer with, in reading order; anything else an agent
// sends is rendered after them rather than dropped.
const FIELD_ORDER = [
  "detected",
  "summary",
  "diagnosis",
  "root_cause",
  "remediation",
  "confidence",
  "findings",
];

const CONFIDENCE_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  high: "success",
  medium: "warning",
  low: "danger",
};

function isFindings(value: unknown): value is AskFinding[] {
  return (
    Array.isArray(value) &&
    value.length > 0 &&
    value.every(
      (v) => typeof v === "object" && v !== null && typeof (v as AskFinding).fact === "string",
    )
  );
}

const present = (v: unknown) =>
  v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);

function FieldValue({ name, value }: { name: string; value: unknown }) {
  if (name === "confidence" && typeof value === "string") {
    return (
      <Badge tone={CONFIDENCE_TONE[value] ?? "neutral"} size="sm">
        {value}
      </Badge>
    );
  }
  if (isFindings(value)) {
    return (
      <ul className="ask-findings">
        {value.map((f, i) => (
          <li key={i} className="ask-finding">
            <span className="ask-finding__fact">{f.fact}</span>
            {f.source ? <span className="ask-finding__source">{f.source}</span> : null}
          </li>
        ))}
      </ul>
    );
  }
  if (typeof value === "string") return <Text variant="body">{value}</Text>;
  if (Array.isArray(value) && value.every((v) => typeof v === "string")) {
    return (
      <ul className="ask-list">
        {value.map((v, i) => (
          <li key={i}>{v}</li>
        ))}
      </ul>
    );
  }
  return <pre className="ask-json">{JSON.stringify(value, null, 2)}</pre>;
}

function Answer({ answer }: { answer: AskAnswer }) {
  const keys = [
    ...FIELD_ORDER.filter((k) => present(answer[k])),
    ...Object.keys(answer).filter((k) => !FIELD_ORDER.includes(k) && present(answer[k])),
  ];
  return (
    <div className="ask-answer">
      <Stack direction="column" gap="md">
        <div className="ask-answer__head">
          <Text variant="h3" as="h2">
            Answer
          </Text>
        </div>
        {keys.length === 0 ? (
          <Text color="muted">The analyst answered with an empty result.</Text>
        ) : (
          keys.map((k) => (
            <div key={k} className="ask-answer__field">
              <Text variant="overline" color="brand">
                {k.replace(/_/g, " ")}
              </Text>
              <FieldValue name={k} value={answer[k]} />
            </div>
          ))
        )}
      </Stack>
    </div>
  );
}

/* --- page ------------------------------------------------------------------ */

/** Behind the door: a question here spends real money on a model.
 *
 *  Guarded in the page as well as in the API. The API is what actually protects
 *  it — this only decides whether to render a form that would be refused, which
 *  is a courtesy rather than a control. */
export function Ask() {
  return (
    <Guard title="Ask">
      <Console />
    </Guard>
  );
}

function Console() {
  const [agents, setAgents] = useState<string[]>(AGENTS_UNTIL_KNOWN);
  const [agent, setAgent] = useState<string>(AGENTS_UNTIL_KNOWN[0]);
  const [model, setModel] = useState<string>(MODELS[0].value);
  // `low`, matching the API's own default for this field — the two disagreed,
  // and the page won, so every question asked from a browser ran at medium while
  // the schema said low. Measured on the public deployment against the same
  // question: **15s at low, 37–89s at medium**, three to five times the wait for
  // an answer a visitor watches arrive. The selector is still here; this only
  // decides what an unattended first click does.
  const [effort, setEffort] = useState<string>("low");
  const [question, setQuestion] = useState("");

  const [phase, setPhase] = useState<Phase>("idle");
  const [run, setRun] = useState<Run | null>(null);
  const [steps, setSteps] = useState<TraceStep[]>([]);
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [spent, setSpent] = useState<AskSpent | null>(null);
  const [reason, setReason] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [silent, setSilent] = useState(false);
  const [traceOpen, setTraceOpen] = useState(true);
  // Whether the composer is showing. Closed the moment a run is under way,
  // because from then on the page's subject is the trace and then the answer —
  // a full-height form sitting above both, disabled, is the largest thing on
  // the page and the least useful. Reopened by "Ask another", which is the only
  // affordance that needs to survive the demotion.
  const [composing, setComposing] = useState(true);

  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [endedAt, setEndedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);

  const esRef = useRef<EventSource | null>(null);
  const doneRef = useRef(false);
  const mountedRef = useRef(true);
  const silenceRef = useRef<number | undefined>(undefined);

  const live = LIVE.includes(phase);

  // The page offers every employee the bus lists, and a name on that list is not
  // a process that is running. An analyst whose process is down never answers:
  // the call sits on the queue until the 15-minute ttl expires and *nothing*
  // comes back in the meantime — no error, no event, just a counter going up.
  // So silence is timed, and after a minute of it the page says what it is
  // probably looking at. It does not cancel: a slow start is real, and a run
  // killed by its own progress bar would be the worse failure.
  const breakSilence = () => {
    window.clearTimeout(silenceRef.current);
    silenceRef.current = undefined;
    setSilent(false);
  };

  // Who is actually on the bus. Fetched once, and failure is survivable: the
  // picker keeps its fallback and the page still works for that one analyst,
  // which is better than an empty select with no explanation.
  useEffect(() => {
    let current = true;
    fetchAgents()
      .then((known) => {
        if (!current || known.length === 0) return;
        setAgents(known);
        setAgent((chosen) => (known.includes(chosen) ? chosen : known[0]));
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, []);

  // A leaked EventSource reconnects forever and re-triggers work, so it is closed
  // on unmount as well as on every terminal event. The silence timer goes with
  // it: a timeout that outlives the page sets state on nothing.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      esRef.current?.close();
      esRef.current = null;
      window.clearTimeout(silenceRef.current);
    };
  }, []);

  useEffect(() => {
    if (!live || startedAt === null) return;
    const id = setInterval(() => setTick(Date.now()), 100);
    return () => clearInterval(id);
  }, [live, startedAt]);

  const elapsedMs = startedAt === null ? 0 : Math.max(0, (endedAt ?? tick) - startedAt);
  const elapsed = formatElapsed(elapsedMs);

  const finish = (next: Phase) => {
    doneRef.current = true;
    esRef.current?.close();
    esRef.current = null;
    breakSilence();
    setEndedAt(Date.now());
    setPhase(next);
  };

  const onEvent = (raw: string) => {
    const ev = parseAskEvent(raw);
    if (!ev) return;
    // Anything at all proves the analyst is there — `started` is what the notice
    // waits for, but a step arriving first says the same thing, and the two
    // travel on different streams so either can land first.
    breakSilence();
    switch (ev.kind) {
      case "started":
        setPhase("running");
        return;
      case "step":
        setPhase("running");
        setSteps((prev) => {
          const step: TraceStep = {
            id: ev.n ?? prev.length + 1,
            kind: ev.step,
            text: ev.text ?? "",
            tool: ev.tool || undefined,
            command: ev.command || undefined,
            skill: ev.skill || undefined,
            durationMs: ev.duration_ms,
            args: ev.args,
          };
          // Inserted in `id` order rather than appended. An out-of-order
          // arrival is normal here, not a fault, and appending would show the
          // run doing things in an order it never did.
          const at = prev.findIndex((seen) => seen.id > step.id);
          return at < 0
            ? [...prev, step]
            : [...prev.slice(0, at), step, ...prev.slice(at)];
        });
        return;
      case "answered":
        setAnswer(ev.answer);
        setSpent(ev.spent ?? null);
        setTraceOpen(false);
        finish("answered");
        return;
      case "failed":
        setReason(ev.reason);
        // Shown for a failure too: a crash after twenty tool calls is exactly
        // the run whose bill somebody wants to see.
        setSpent(ev.spent ?? null);
        setTraceOpen(false);
        finish("failed");
        return;
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (live || !question.trim()) return;

    esRef.current?.close();
    esRef.current = null;
    doneRef.current = false;
    setSteps([]);
    setAnswer(null);
    setSpent(null);
    setReason(null);
    setNotice(null);
    setRun(null);
    setStartedAt(null);
    setEndedAt(null);
    setTraceOpen(true);
    setPhase("starting");
    breakSilence();

    const started = await startAsk({ agent, model, effort, question: question.trim() });
    if (!mountedRef.current) return;
    if (!started.ok) {
      // A 409 is the expected "already busy" reply — reported, not dressed up as
      // a failure.
      setNotice(started.detail);
      setPhase(started.busy ? "idle" : "error");
      return;
    }

    setRun({ agent, model, effort, question: question.trim(), reference: started.reference });
    // Only once the analyst has actually taken the question: a 409 or a POST
    // that didn't land leaves the composer where it is, with the answer to why
    // right underneath it.
    setComposing(false);
    setStartedAt(Date.now());
    setTick(Date.now());
    setPhase("open");
    silenceRef.current = window.setTimeout(() => {
      if (mountedRef.current) setSilent(true);
    }, SILENCE_MS);

    const es = new EventSource(askEventsUrl(started.reference));
    esRef.current = es;
    // A frame carries either no `event:` field (onmessage) or a named one, never
    // both, so listening for both covers either server style without doubling.
    es.onmessage = (m: MessageEvent<string>) => onEvent(m.data);
    for (const name of ["started", "step", "answered", "failed"]) {
      es.addEventListener(name, (m) => onEvent((m as MessageEvent<string>).data));
    }
    es.onerror = () => {
      // After a terminal event the server closing is expected; before one, the
      // stream dropped. Either way the source is closed rather than left to
      // reconnect and start the work again.
      if (doneRef.current) return;
      setTraceOpen(true);
      finish("lost");
    };
  };

  const onQuestionKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.currentTarget.form?.requestSubmit();
    }
  };

  const status = STATUS[phase];

  return (
    <Stack direction="column" gap="lg">
      <div className="ask-intro">
        <Stack direction="column" gap="2xs">
          <Text variant="overline" color="brand">
            ANALYSTS
          </Text>
          <Text variant="h2" as="h1">
            Ask an analyst
          </Text>
          <Text variant="body" color="muted">
            Put a question to one of the company's AI analysts and watch it work — every
            command it runs and every answer it reads, as it happens.
          </Text>
        </Stack>
      </div>

      {/* One console rather than a form card and a run card: who was asked, what
          was asked and how it is going are the same object at two moments of its
          life. `data-lead` is the page's whole hierarchy rule — exactly one block
          carries the lift, and it moves from here to the trace to the answer. */}
      <section className="ask-console" data-lead={run ? undefined : ""}>
        {run ? (
          <div className="ask-run">
            <div className="ask-run__line">
              <Badge tone={status.tone} size="sm">
                {live ? <span className="ask-dot" aria-hidden="true" /> : null}
                {status.label}
              </Badge>
              <span className="ask-run__spec">
                {run.agent} · {run.model} · {run.effort}
              </span>
              <span className="ask-run__meters">
                <span className="ask-run__meter">
                  <b>{elapsed.value}</b>
                  {elapsed.unit}
                </span>
                <span className="ask-run__meter">
                  <b>{steps.length}</b>
                  {steps.length === 1 ? "step" : "steps"}
                </span>
              </span>
              {live || composing ? null : (
                <button
                  type="button"
                  className="ask-again"
                  onClick={() => setComposing(true)}
                >
                  Ask another
                </button>
              )}
            </div>
            <Text variant="title" as="h2">
              {run.question}
            </Text>
            <span className="ask-run__ref">ref {run.reference}</span>
          </div>
        ) : null}

        {composing ? (
          <form className="ask-form" onSubmit={submit}>
            <div className="ask-controls">
              {/* The analyst is the choice that changes the answer; the model and
                  the effort only change how hard it is thought about. So one lead
                  control and two refinements, not three peers in a row. */}
              <div className="ask-pick ask-pick--lead">
                <label className="ask-pick__label" htmlFor="ask-analyst">
                  Analyst
                </label>
                <span className="ask-pick__field">
                  <select
                    id="ask-analyst"
                    className="ask-select"
                    value={agent}
                    disabled={live}
                    onChange={(e) => setAgent(e.target.value)}
                  >
                    {agents.map((a) => (
                      <option key={a} value={a}>
                        {a}
                      </option>
                    ))}
                  </select>
                </span>
              </div>
              <div className="ask-refine">
                <div className="ask-pick">
                  <label className="ask-pick__label" htmlFor="ask-model">
                    Model
                  </label>
                  <span className="ask-pick__field">
                    <select
                      id="ask-model"
                      className="ask-select"
                      value={model}
                      disabled={live}
                      onChange={(e) => setModel(e.target.value)}
                    >
                      {MODELS.map((m) => (
                        <option key={m.value} value={m.value}>
                          {m.label}
                        </option>
                      ))}
                    </select>
                  </span>
                </div>
                <div className="ask-pick">
                  <label className="ask-pick__label" htmlFor="ask-effort">
                    Effort
                  </label>
                  <span className="ask-pick__field">
                    <select
                      id="ask-effort"
                      className="ask-select"
                      value={effort}
                      disabled={live}
                      onChange={(e) => setEffort(e.target.value)}
                    >
                      {EFFORTS.map((x) => (
                        <option key={x} value={x}>
                          {x}
                        </option>
                      ))}
                    </select>
                  </span>
                </div>
              </div>
            </div>

            <div className="ask-question">
              <label className="ask-sr" htmlFor="ask-question">
                Your question
              </label>
              <textarea
                id="ask-question"
                className="ask-textarea"
                rows={3}
                value={question}
                disabled={live}
                placeholder={PLACEHOLDER}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={onQuestionKey}
              />
            </div>

            <div className="ask-actions">
              <span className="ask-hint">
                Plain language. One analyst at a time — <kbd className="ask-key">{MOD_KEY}</kbd>
                <kbd className="ask-key">↵</kbd> to send.
              </span>
              <button type="submit" className="ask-submit" disabled={live || !question.trim()}>
                {live ? "Working…" : `Ask ${agent}`}
              </button>
            </div>
          </form>
        ) : null}
      </section>

      {notice ? (
        <div className="ask-notice" data-tone={phase === "error" ? "error" : "busy"} role="status">
          <Badge tone={phase === "error" ? "danger" : "warning"} size="sm">
            {phase === "error" ? "not started" : "busy"}
          </Badge>
          <span>{notice}</span>
        </div>
      ) : null}

      {run ? (
        <>
          {silent && live ? (
            <div className="ask-notice ask-notice--silent" role="status">
              <Badge tone="warning" size="sm">
                no reply yet
              </Badge>
              <span>
                <strong>{run.agent} has not said anything in a minute.</strong> Every name on
                the picker needs its own process running on the bus, and one that is down
                takes questions without ever answering them — this is what that looks like.
                The run has not been cancelled: a slow start looks the same from here, and it
                will keep going until it answers or its fifteen-minute deadline passes.
              </span>
            </div>
          ) : null}

          <Trace
            steps={steps}
            open={traceOpen}
            onToggle={() => setTraceOpen((v) => !v)}
            elapsed={`${elapsed.value}${elapsed.unit}`}
            live={live}
          />

          {phase === "lost" ? (
            <div className="ask-answer ask-answer--warn">
              <Stack direction="column" gap="xs">
                <Text variant="h3" as="h2">
                  Connection lost
                </Text>
                <Text variant="body" color="muted">
                  The stream dropped after {steps.length}{" "}
                  {steps.length === 1 ? "step" : "steps"}, before an answer arrived. What
                  came through is above — the analyst may still be working; ask again to
                  start a new run.
                </Text>
              </Stack>
            </div>
          ) : null}

          {phase === "failed" ? (
            <div className="ask-answer ask-answer--fail">
              <Stack direction="column" gap="xs">
                <Text variant="h3" as="h2">
                  The run failed
                </Text>
                <Text variant="body" color="muted">
                  {reason}
                </Text>
              </Stack>
            </div>
          ) : null}

          {answer ? <Answer answer={answer} /> : null}

          {spent ? <Spent spent={spent} /> : null}
        </>
      ) : null}
    </Stack>
  );
}
