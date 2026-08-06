"""The two drivers, on the parts that do not need a model.

Building, opencode's answer extraction, and what each loop reports it spent. The
extraction earns a test because opencode has no `--output-schema`: the shape is
asked for in words and can arrive wrapped in prose, so digging it out is real
logic rather than a parse. The accounting earns one because each driver now does
its own, and the two vendors do not mean the same thing by "input tokens".

**Which loop an employee runs on is deliberately not tested here.** That choice
is the employee's — `identity.build` picks a driver from its own configuration —
and a shared package that decided it would be deciding what distinguishes them.
"""

import inspect
import json
import pathlib

from core.config import (
    Config,
    FeedConfig,
    LokiConfig,
    MatomoConfig,
    ModelConfig,
    QueueConfig,
    ShopConfig,
)
from core.harness import codex, opencode_cli
from core.harness.codex import CodexHarness
from core.harness.codex import _usage as codex_usage
from core.harness.desk import CA_FILE, DATA, Desk, prepare
from core.harness.opencode_api import usage as opencode_usage
from core.harness.opencode_api import verdict as _verdict
from core.harness.opencode_cli import OpencodeHarness
from core.harness.opencode_cli import server_config as opencode_config

DESK = Desk(root=pathlib.Path("desk"))
"""Stands in for an employee's own. Nothing here reaches the filesystem."""


def config(model: str = "a-model", effort: str = "") -> Config:
    """A deployment, with only the two fields a CLI driver reads set.

    Built rather than loaded, so nothing in this file depends on an environment
    or a `.env` that happens to be beside the test run.
    """
    return Config(
        model=ModelConfig(name=model, base_url="", api_key="", reasoning=effort),
        shop=ShopConfig(base_url="", api_key="", timezone="UTC"),
        matomo=MatomoConfig(base_url="", token="", site_id="1"),
        loki=LokiConfig(base_url=""),
        queue=QueueConfig(url="", namespace=""),
        feed=FeedConfig(host="", port=22, user="", password="", directory=""),
        timeout_s=1.0,
    )


def test_each_driver_builds_the_loop_it_names() -> None:
    assert isinstance(codex.build(config(), DESK), CodexHarness)
    assert isinstance(opencode_cli.build(config(), DESK), OpencodeHarness)


def test_the_desk_is_the_employee_s_rather_than_the_library_s() -> None:
    """It used to be computed from `__file__`, which was right while this code
    sat inside one employee's package. From a shared one `__file__` resolves
    into the library, so every employee would be handed the same desk — and the
    desk is the whole of what distinguishes them."""
    mine = Desk(root=pathlib.Path("/somewhere/else/desk"))

    assert codex.build(config(), mine)._desk is mine
    assert opencode_cli.build(config(), mine)._desk is mine


def test_the_model_reaches_whichever_loop_was_chosen() -> None:
    assert codex.build(config("gpt-5.6-luna"), DESK)._model == "gpt-5.6-luna"
    assert opencode_cli.build(config("gpt-5.6-luna"), DESK)._model == "gpt-5.6-luna"


def verdict(detected: str, confidence: str = "high") -> str:
    """One answer of the shape `ANSWER_SCHEMA` requires, as a model would print it.

    A helper rather than a literal in each test: these fixtures are only valid
    because they satisfy the schema, so when the schema gains a required field
    every one of them has to gain it too. Writing them out by hand is how a
    fixture quietly stops being an answer and the test starts asserting that
    `_verdict` rejects things.
    """
    return json.dumps(
        {
            "detected": detected,
            "diagnosis": "d",
            "root_cause": "r",
            "remediation": "m",
            "confidence": confidence,
            "findings": [{"fact": "f", "source": "shop"}],
        }
    )


def test_the_verdict_survives_surrounding_prose() -> None:
    text = f"Here is what I found.\n{verdict('s')}\nHope that helps."

    found = _verdict(text)

    assert found is not None and found["detected"] == "s"


def test_the_last_matching_object_wins() -> None:
    """A model that reasons before answering often prints a draft on the way."""
    text = f"{verdict('draft', 'low')}\n{verdict('final')}"

    found = _verdict(text)

    assert found is not None and found["detected"] == "final"


def test_an_answer_missing_a_required_field_is_not_a_verdict() -> None:
    """The old three-field shape, which every earlier run answered in.

    It parses as JSON and reads like an answer, and that is the point: without
    the schema check a model that skipped `remediation` would be recorded as
    having answered, and "no fix proposed" would be indistinguishable from "no
    fix needed".
    """
    text = '{"summary": "s", "diagnosis": "d", "confidence": "high"}'

    assert _verdict(text) is None


def test_effort_reaches_whichever_loop_was_chosen() -> None:
    """The setting must survive `build`, for both drivers.

    It is wired here rather than asserted on a live run because it is the one
    lever measured to move wall clock: the same model spent 8-10k reasoning
    tokens per investigation under codex and 1-2k under opencode, and those runs
    were 7x apart in time while their contexts were not.
    """
    assert codex.build(config(effort="low"), DESK)._effort == "low"
    assert opencode_cli.build(config(effort="low"), DESK)._effort == "low"


def test_no_effort_leaves_each_harness_on_its_own_default() -> None:
    """Unset must send no *effort* — but the model is declared regardless.

    The earlier version of this asserted no `provider` block at all, and that
    assertion was the bug: opencode learns the model from that block, so
    omitting it made every run without an effort fail with
    `ProviderModelNotFoundError` — a 2xx with an empty body that the driver
    reported as a malformed answer. Campaigns passed an effort and worked;
    everything else did not.
    """
    assert codex.build(config(), DESK)._effort == ""

    declared = opencode_config("openai", "gpt-5.6-luna", "")["provider"]["openai"]
    assert "gpt-5.6-luna" in declared["models"]
    assert declared["models"]["gpt-5.6-luna"]["options"] == {}


CODEX_TURN = {
    "type": "turn.completed",
    "usage": {
        "input_tokens": 10_303,
        "cached_input_tokens": 6_942,
        "output_tokens": 1_036,
        "reasoning_output_tokens": 647,
    },
}
"""One turn's accounting, in codex's own shape: `input_tokens` INCLUDES the
cached subset reported beside it."""


def opencode_message(
    sent: int, received: int, reasoning: int, cached: int, cost: float
) -> dict:
    """One assistant message's accounting, in opencode's shape.

    `input` here EXCLUDES the cached tokens, which is the whole difficulty.
    """
    return {
        "info": {
            "role": "assistant",
            "cost": cost,
            "tokens": {
                "input": sent,
                "output": received,
                "reasoning": reasoning,
                "cache": {"read": cached, "write": 0},
            },
        },
        "parts": [],
    }


def test_codex_reports_what_its_turn_spent() -> None:
    """Without this a campaign's cost tables are blank, and those tables carry
    one of the lab's firmest findings: two analysts reaching the same diagnosis
    seventeen token-fold apart."""
    spent = codex_usage([{"type": "thread.started"}, dict(CODEX_TURN)])

    assert spent.input_tokens == 10_303
    assert spent.output_tokens == 1_036
    assert spent.reasoning_tokens == 647
    assert spent.cache_read_tokens == 6_942


def test_codex_does_not_invent_a_request_count() -> None:
    """It says what a turn cost and never how many requests it took to spend it.
    Counting turns instead would report `1` for an investigation that called the
    model forty times, and a figure the driver invented is a figure the lab
    could publish wrong."""
    spent = codex_usage([dict(CODEX_TURN)])

    assert spent.model_requests == 0
    assert spent.cost is None


def test_a_turn_that_reported_nothing_costs_nothing_rather_than_crashing() -> None:
    """A killed run still has to produce a record."""
    assert codex_usage([]).input_tokens == 0


def test_opencode_sums_the_messages_that_spent_something() -> None:
    """It reports per message and a turn is many messages, so these are summed
    rather than taken from the last one. Reading only codex's shape left every
    opencode cost cell empty, which the report rendered as a dash and a reader
    could easily have taken for a cheap run rather than an unmeasured one."""
    spent = opencode_usage(
        [
            opencode_message(1_000, 100, 40, 2_000, 0.01),
            opencode_message(2_361, 936, 607, 4_942, 0.02),
        ]
    )

    assert spent.model_requests == 2
    assert spent.output_tokens == 1_036
    assert spent.reasoning_tokens == 647
    assert spent.cost == 0.03


def test_a_message_that_spent_nothing_is_not_a_model_request() -> None:
    """One assistant message is one model request, which is the count codex
    cannot give. The ticket itself is not one."""
    spent = opencode_usage(
        [{"info": {"role": "user"}, "parts": []},
         opencode_message(1_000, 100, 40, 2_000, 0.01)]
    )

    assert spent.model_requests == 1


def test_a_run_whose_provider_had_no_price_is_unmeasured_not_free() -> None:
    """Zero becomes `None`: a dash a reader can question, rather than a figure
    that says the investigation was free."""
    spent = opencode_usage([opencode_message(10, 1, 0, 0, 0.0)])

    assert spent.cost is None


def test_both_loops_count_everything_that_was_sent() -> None:
    """The reconciliation, asserted on the same run counted two ways.

    codex's `input_tokens` includes its cached subset; opencode's excludes it
    and reports `total = input + output + cache.read`. Left unreconciled, one
    column held two different quantities and a campaign compared a
    cache-inclusive figure against a cache-exclusive one — a ~7x difference on a
    real record. Both normalise to "everything sent", with the cached part
    reported separately.
    """
    by_codex = codex_usage([dict(CODEX_TURN)])
    by_opencode = opencode_usage([opencode_message(3_361, 1_036, 647, 6_942, 0.0)])

    assert by_codex.input_tokens == by_opencode.input_tokens == 10_303
    assert by_codex.cache_read_tokens == by_opencode.cache_read_tokens == 6_942


def test_both_drivers_build_the_child_environment_rather_than_inheriting() -> None:
    """What a model-written shell can reach is a decision, not a leftover.

    Each driver hands a subprocess the environment it will run under, and that
    environment is the access boundary the whole lab varies: the credentials in
    it are what an employee can use, and the ones absent from it are what the
    experiment says it cannot. Built from an allow-list, that boundary is
    stated. Merged from `os.environ`, it is whatever happened to be exported —
    the analyst's Redis URL, another employee's key, a CI token.

    This guarantee used to be asserted in each agent's own suite, against an
    agent module that no longer builds anything. It moved here with the drivers
    and very nearly did not: for a while nothing checked it at all, which is
    exactly how a boundary stops being one.
    """
    for module in (codex, opencode_cli):
        source = inspect.getsource(module)
        assert "child_env(" in source, f"{module.__name__} builds no child env"
        assert "**os.environ" not in source, f"{module.__name__} inherits wholesale"
        assert "os.environ.copy()" not in source


def test_the_desk_is_laid_out_before_the_loop_starts(tmp_path) -> None:
    """The step that fell between two chairs.

    Each agent's own service used to call `prepare` one line before handing the
    workspace to its loop. When that service moved into this package the call
    had nowhere to go — `run.investigate` knows nothing about desks, and rightly
    — and it was lost. Nothing failed: the loop started in an empty directory
    with no skills, no brief and no certificate, and reported an investigation
    that had nothing to investigate with.

    Asserted on the driver rather than on `prepare`, because `prepare` was never
    the thing that broke. Both desk-driven loops are checked: they are separate
    call sites and only one of them being right is the failure itself.
    """
    root = tmp_path / "desk"
    (root / "skills" / "shop-webservice").mkdir(parents=True)
    (root / "skills" / "shop-webservice" / "SKILL.md").write_text("how to read it")
    (root / "AGENTS.md").write_text("who you are")
    (root / CA_FILE).write_text("-----BEGIN CERTIFICATE-----")

    for index, module in enumerate((codex, opencode_cli)):
        workdir = tmp_path / f"work{index}"
        workdir.mkdir()
        loop = module.build(config(), Desk(root=root))

        # Only the layout is wanted, so the loop itself is never started.
        prepare(loop._desk, workdir)  # noqa: SLF001 - the desk it was handed

        assert (workdir / "AGENTS.md").is_file(), f"{module.__name__}: no brief"
        assert (workdir / ".agents" / "skills" / "shop-webservice").is_dir()
        assert (workdir / CA_FILE).is_file()
        assert (workdir / DATA).is_dir()

    assert "prepare(self._desk, workdir)" in inspect.getsource(codex)
    assert "prepare(self._desk, workdir)" in inspect.getsource(opencode_cli)
