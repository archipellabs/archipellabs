"""Where an agent's model and credentials come from.

Two rules hold this together:

* **One code path for every model.** LM Studio, vLLM and OpenAI all speak the
  OpenAI protocol, so the difference between "local 26B for tests" and "a hosted
  model in production" is three environment variables, never a branch. Being able
  to swap the model without touching anything else is what lets a bad run be
  *attributed* — "the role could not see it" and "the model could not drive the
  loop" look identical otherwise.

* **Secrets never reach the model.** Credentials are read here and used by the
  HTTP clients; no tool takes a token as an argument, and no tool signature
  mentions one. The agent knows it can read the shop, not what key opens it.
"""

import os
import pathlib
import sys
from dataclasses import dataclass, replace

REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
"""Every depth the model API itself accepts.

**Transcribed from the installed OpenAI SDK's `ReasoningEffort`, not invented
here** — the value is interpreted nowhere in this repository: it is handed to
`openai_reasoning_effort`, or to a CLI's own flag, and travels to the provider
unchanged. A list of our own would drift from that one, and the drift shows up
as a request rejected mid-investigation.

Transcribed rather than imported, and a test asserts the two still agree. The
SDK keeps this list at an internal path; importing it would make an upstream
reshuffle break every employee at boot, which is a worse failure than the drift
it prevents. A failing test is the cheap, loud version of the same alarm.

Wider than what anyone should routinely pick — `medium` is the floor for a fair
comparison, and `none` is close to benchmarking a crippled model. Choosing badly
is the caller's business; choosing a word no provider knows is what this
refuses."""


def checked_effort(effort: str) -> str:
    """One reasoning effort, lowered and checked against what the API takes.

    Refused here rather than passed through. Sent on, an unknown depth comes
    back as a 400 from the provider on the first turn — which arrives at a
    caller as an investigation that crashed, indistinguishable in the envelope
    from a model that fell over doing real work.

    Empty means "not chosen", which is a different thing from wrong: it leaves
    whatever the environment already said in place.
    """
    chosen = effort.strip().lower()
    if chosen and chosen not in REASONING_EFFORTS:
        raise ValueError(
            f"effort must be one of {', '.join(REASONING_EFFORTS)}, not {effort!r}"
        )
    return chosen


def _load_dotenv() -> None:
    """Read the current employee's .env, without overriding a set variable.

    Called from `load()` rather than from one entrypoint: the CLI had it and the
    queue service did not, so a ticket arriving over the queue reached a process
    with no model credentials and came back as a RemoteError. Configuration
    belongs to the config module, not to whichever main happened to need it
    first. A container gets its environment from compose, so this is a no-op
    there.
    """
    configured = os.getenv("AGENT_ENV_FILE")
    candidates = (
        [pathlib.Path(configured)]
        if configured
        else [pathlib.Path.cwd() / ".env", pathlib.Path(sys.path[0]) / ".env"]
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


@dataclass(frozen=True)
class ModelConfig:
    name: str
    base_url: str
    api_key: str
    api: str = "chat"
    """Which OpenAI-shaped endpoint to speak: `chat` or `responses`.

    The one place the "no branch per model" rule bends, and only because the two
    are different HTTP surfaces rather than different behaviour. A reasoning model
    refuses function tools on /v1/chat/completions — "use /v1/responses or set
    reasoning_effort to 'none'" — and turning reasoning off to keep one code path
    would mean benchmarking a crippled model. Still configuration, not a branch on
    the model's name."""
    reasoning: str = "medium"
    """How hard the model is asked to think. Pinned, and shared by every employee.

    Left unset, each harness took its own default: pydantic-ai sent nothing and
    let the API decide, while opencode sent reasoning parameters of its own — it
    was caught doing so by an `Unknown parameter: reasoningSummary` rejection.
    Two harnesses thinking at different depths cannot be compared, and the
    difference would have been read as a property of the harness.

    `medium` is the floor rather than the cheapest option: `low` on a reasoning
    model is close to benchmarking a crippled one, which is the same mistake as
    turning reasoning off to keep a single code path."""


@dataclass(frozen=True)
class ShopConfig:
    """PrestaShop's legacy Webservice — the read-only key, not the integration's."""

    base_url: str
    api_key: str
    timezone: str
    """The clock the shop stamps its own records in.

    Carried here because the agent cannot discover it: `configurations` is
    refused to a read-only key, so PS_TIMEZONE is unreachable through the API. A
    run compared an order at 14:30 shop-time against a log line at 19:28 UTC and
    concluded orders had stopped five hours earlier — they were minutes old. Must
    match PS_TIMEZONE in the shop's own environment."""

    ca: str = ""
    """What `--cacert` should trust, as `$COMPANY_CA`. Empty means the desk's own
    `company-ca.crt`.

    The skills pin `--cacert "$COMPANY_CA"` rather than trusting whatever the
    system trusts, because the local company answers on `.test` names behind a
    self-signed certificate and plain `curl` reads as an unreachable system.

    Pinning cuts the other way on a deployment whose certificate is signed by a
    public authority: the desk's file is then the *wrong* CA, every call fails
    verification, and it fails identically to the shop being down. Such a
    deployment sets this to its trust store — `/etc/ssl/certs/ca-certificates.crt`
    in this image — which makes the pin equivalent to ordinary verification."""


@dataclass(frozen=True)
class MatomoConfig:
    base_url: str
    token: str
    site_id: str


@dataclass(frozen=True)
class QueueConfig:
    """Where tickets arrive and where the analyst narrates.

    The same Redis the simulator uses, and the same namespace, because that is
    what makes `ctx.call("analyst.investigate")` reach this process. Transport
    only — sharing a queue is not sharing a database.
    """

    url: str
    namespace: str


@dataclass(frozen=True)
class LokiConfig:
    base_url: str


@dataclass(frozen=True)
class FeedConfig:
    """The ERP's file drop, over SFTP. Read-only for this identity."""

    host: str
    port: int
    user: str
    password: str
    directory: str


@dataclass(frozen=True)
class Config:
    model: ModelConfig
    shop: ShopConfig
    matomo: MatomoConfig
    loki: LokiConfig
    queue: QueueConfig
    feed: FeedConfig
    # Appended, with defaults, and that is deliberate rather than tidy: a test
    # suite builds this positionally, so inserting a field anywhere above would
    # mis-assign every argument after it without raising.
    harness: str = ""
    """Which loop drives the investigation, for the employees that have a choice.

    Empty means the employee has only one, which is the common case — the
    pydantic-ai lineage is its loop. Configurable at all because the loop is a
    variable under test, not a settled choice."""
    timeout_s: float = 900.0
    """Generous, but finite: an unbounded run holds the employee's single slot
    forever, and the caller is already waiting behind its own ttl."""

    def for_call(self, model: str | None = None, effort: str | None = None) -> Config:
        """This configuration as one caller asked for it — as a copy.

        The environment stays the default and the ticket overrides it, which is
        what lets a portal offer a model and a depth per question rather than
        per deployment. Only those two move: the credentials, the shop's clock
        and the queue are the employee's identity, not a caller's to choose.

        Two copies rather than one mutation, because `ModelConfig` is nested and
        `replace` is shallow. Written in place instead, the choice would survive
        the request that made it — the process outlives every ticket, and the
        next investigation would run at a depth nobody asked for while its
        transcript still named the deployment's own setting.

        Blank counts as unchosen. `AGENT_MODEL_REASONING` empty falls back to
        `medium` in `load()`, so an empty string here would not mean anything a
        caller could have intended.

        **A chosen depth only reaches a `responses` deployment.** `api` stays
        the environment's, and on `chat` the agent sends no reasoning parameter
        at all — see `agent.build`. So a caller picking `high` against a local
        chat-completions server changes nothing, silently. That is the existing
        behaviour of the setting rather than something this introduced, but it
        is now reachable by whoever asks rather than only by whoever deploys,
        and a picker that appears to do nothing is worth knowing about before it
        is offered.
        """
        # Checked here as well as at the queue's edge. The ticket model catches a
        # typo arriving over the bus, but a campaign or a test calling this
        # directly bypasses it entirely, and an unvalidated depth reaches the
        # provider as a 400 mid-run that arrives looking like a crashed analyst.
        chosen = checked_effort(effort) if effort else ""
        return replace(
            self,
            model=replace(
                self.model,
                name=(model or "").strip() or self.model.name,
                reasoning=chosen or self.model.reasoning,
            ),
        )


def load(agent: str = "") -> Config:
    """The deployment's configuration, with this employee's own settings on top.

    `agent` selects a per-employee prefix — `PHILIP_HARNESS`, `PHILIP_EFFORT` —
    read before the shared names. A campaign schedules several employees in one
    process tree and passes each one's axis that way, so a shared variable would
    hand both the same loop and report two identical cells as a comparison.
    """
    _load_dotenv()
    prefix = agent.upper()

    def mine(suffix: str, shared: str, default: str = "") -> str:
        """This employee's setting, else the shared one, else the default."""
        own = _env(f"{prefix}_{suffix}") if prefix else ""
        return own or _env(shared, default)

    return Config(
        harness=mine("HARNESS", "AGENT_HARNESS"),
        timeout_s=float(mine("TIMEOUT_S", "AGENT_TIMEOUT_S", "900")),
        model=ModelConfig(
            # Defaults target LM Studio on the developer's machine. From inside a
            # container the host is host.docker.internal, which is why the URL is
            # configured rather than assumed.
            name=mine("MODEL", "AGENT_MODEL_NAME", "google/gemma-4-26b-a4b"),
            base_url=_env("AGENT_MODEL_BASE_URL", "http://localhost:1234/v1"),
            # LM Studio ignores the key but the OpenAI client insists on one.
            api=_env("AGENT_MODEL_API", "chat"),
            # `<AGENT>_EFFORT` first: a campaign crossing two depths sets it per
            # employee, and reading only the shared name would leave one analyst
            # at its own default while the other moved — a report comparing two
            # efforts while having compared one.
            reasoning=mine("EFFORT", "AGENT_MODEL_REASONING", "medium"),
            # Falls back to OPENAI_API_KEY so a hosted key lives in exactly one
            # variable. A local server ignores the key entirely, so the fallback
            # costs nothing when pointing at LM Studio.
            api_key=_env("AGENT_MODEL_API_KEY") or _env("OPENAI_API_KEY"),
        ),
        shop=ShopConfig(
            base_url=_env("SHOP_API_URL", "https://shop.archipellabs.test/api"),
            api_key=_env("AGENT_API_KEY"),
            timezone=_env("SHOP_TIMEZONE", "America/Chicago"),
            ca=_env("COMPANY_CA"),
        ),
        matomo=MatomoConfig(
            base_url=_env("MATOMO_URL", "https://tracking.archipellabs.test"),
            token=_env("MATOMO_AGENT_TOKEN"),
            site_id=_env("MATOMO_SITE_ID", "1"),
        ),
        # Not published outside the compose network, so an agent that needs logs
        # runs inside it.
        loki=LokiConfig(base_url=_env("LOKI_URL", "http://loki:3100")),
        queue=QueueConfig(
            # One name each. `REDIS_URL` and `REDIS_NAMESPACE` were honoured as
            # well while two employees kept their own `.env` files saying that;
            # there is one file now, so the second spelling has nothing left to
            # rescue and keeping it would only let a future file drift back.
            url=_env("AGENT_REDIS_URL", "redis://localhost:6379/0"),
            namespace=_env("AGENT_NAMESPACE", "sim"),
        ),
        feed=FeedConfig(
            host=_env("FEED_HOST", "erpfile"),
            port=int(_env("FEED_PORT", "22")),
            user=_env("FEED_USER", "agent"),
            password=_env("FEED_PASSWORD", "agent"),
            directory=_env("FEED_DIR", "data"),
        ),
    )
