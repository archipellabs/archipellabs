"""The desk must document systems, never investigations.

This is the rule the README states and that nothing enforced. A security review
found it broken in two of the three live scenarios: `analytics-matomo` carried
the graded conclusion of `conversion_funnel` almost word for word — *"the two
cannot be composed into one funnel"* — and `erp-feed` carried the declared
difficulty of `carrier_withdrawn` as a section heading, *"Nothing errors when a
feed changes"*.

A campaign over a contaminated desk measures the desk. The 3/3 that Ethan scored
on the funnel had to be withdrawn for exactly this.

The check is deliberately a keyword blacklist rather than anything clever. It
cannot prove neutrality, and a model could restate any of these in other words.
It exists to catch the specific sentences that were found, so that removing them
stays removed, and to make the rule visible to whoever edits a skill next.

The machinery is `core.harness.desk`; the desk itself is Ethan's, and it is
the desk that is on trial here. Nothing below reaches for the shared module's own
paths, because the shared module has none: `DESK.root` is where this employee's
material lives, and a test that asked the library where the desk was would be
testing every employee's desk at once, which is to say none of them.
"""

import pathlib

import pytest

from core.harness import desk
from roles.ethan.identity import DESK

SKILLS = sorted((DESK.root / "skills").glob("*/SKILL.md"))


def flat(text: str) -> str:
    """Lowercased with every run of whitespace collapsed to one space.

    Without this the blacklist is defeated by the line width. The desk wraps at
    about 78 characters, so a forbidden phrase lands across a newline roughly as
    often as not, and a substring check then sails straight past it. The brief's
    *"they may be / counting different things"* was wrapped exactly that way and
    would have gone on passing.
    """
    return " ".join(text.split()).lower()

FORBIDDEN = {
    # conversion_funnel — its graded conclusion is that the two sides count
    # different populations and cannot be nested into one sequence. Saying so
    # here answers the ticket.
    "cannot be composed": "conversion_funnel's graded conclusion",
    "can be compared": "conversion_funnel's graded conclusion",
    # carrier_withdrawn — its stated difficulty is that nothing errors, so the
    # signal is an absence. Naming that is naming the answer.
    "nothing errors": "carrier_withdrawn's declared difficulty",
    "invisible to anything": "carrier_withdrawn's declared difficulty",
    "it is an instruction": "carrier_withdrawn's mechanism",
    # conversion_funnel again, and this is the round that mattered. The first
    # pass removed the sentence that stated the conclusion and left the
    # paragraph that explains the mechanism, which is the same answer with more
    # words. A campaign then ran over it: 89% of Ethan's runs pulled one of
    # these strings into context, and the runs that did scored 76% against 62%
    # for the runs that did not. Each phrase below is quoted from the desk as it
    # shipped that day.
    "visits are not records": "conversion_funnel's graded conclusion",
    "no shared key": "conversion_funnel — why the two cannot be joined",
    "reaches the tracker": "conversion_funnel — the under-count, handed over",
    "counting different things": "conversion_funnel's method, from the brief",
    "before comparing them": "conversion_funnel's method, from the brief",
    # Method in general: a skill that says where to start makes every run a test
    # of that hint.
    "when orders drop": "investigation method",
    "start by checking": "investigation method",
}


@pytest.mark.parametrize("skill", SKILLS, ids=[p.parent.name for p in SKILLS])
def test_a_skill_documents_its_system_and_not_an_investigation(
    skill: pathlib.Path,
) -> None:
    text = flat(skill.read_text())
    found = [f"{phrase!r} ({why})" for phrase, why in FORBIDDEN.items() if phrase in text]

    assert not found, (
        f"{skill.parent.name} hands the agent a conclusion: {'; '.join(found)}. "
        "A skill documents a system; method belongs to the ticket."
    )


def test_the_brief_names_no_system_to_start_from() -> None:
    """`AGENTS.md` says how to work, never what to look for.

    Naming where to begin would make every run a test of that hint rather than
    of whether the company can be understood.

    **What the company is stays in.** It sells wood to the United States and
    Canada, which is the map: `_core`'s brief carries it for the four typed
    analysts, so withholding it here would compare briefs rather than desks. What
    must not be here is the territory — which market is failing, and why.
    """
    brief = flat(desk.brief(DESK))

    for phrase, why in FORBIDDEN.items():
        assert phrase not in brief, f"the brief carries {phrase!r} ({why})"


def test_the_blacklist_would_actually_fire() -> None:
    """A guard nobody has seen fail is a guard nobody should trust.

    Every phrase below is quoted from a desk that actually shipped: the first
    two lines from the morning, the rest from the version that survived the
    first cleanup and still carried the answer through a 72-run campaign.
    """
    was_shipped = (
        "The two cannot be composed into one funnel. They can be compared.\n"
        "## Nothing errors when a feed changes\n"
        "**Visits are not records.** Matomo counts visits: one person, one\n"
        "session. There is no shared key between them, and roughly a tenth of\n"
        "activity never reaches the tracker at all.\n"
        "Two systems disagreeing is normal: they may be counting different\n"
        "things. Establish what each one counts before comparing them.\n"
    )
    was_shipped = flat(was_shipped)

    hits = [p for p in FORBIDDEN if p in was_shipped]

    assert len(hits) >= 8


def test_the_child_environment_is_built_not_inherited() -> None:
    """Ethan's own machinery must not reach a shell the model writes.

    This was decoration until now: both drivers merged `os.environ`, and only
    codex refiltered it afterwards through a setting of its own. opencode has no
    such setting, so a `bash: allow` loop could read `REDIS_URL` and write onto
    Ethan's own action stream — the investigated system driving the
    investigator.

    Asked of **Ethan's** desk rather than of the builder in the abstract. The
    allow-list is a field on `Desk` now, so what a shell can reach is this
    employee's to state and this employee's to get wrong; a version of this test
    that constructed its own desk would pass over an agent that had widened its
    own.
    """
    import os

    os.environ["AGENT_REDIS_URL"] = "redis://should-not-leak:6379/0"
    os.environ["ETHAN_HARNESS"] = "codex"
    # Put the shop's address in the environment under the name the *skills* use,
    # so a passthrough would be invisible: the assertion below only means
    # something because the value it expects is the configured one, not this.
    os.environ["SHOP_API_URL"] = "https://leaked-from-the-environment.test/api"

    given = desk.child_env(DESK, _config())

    assert "AGENT_REDIS_URL" not in given
    assert not [k for k in given if k.startswith("ETHAN_")]
    assert given["SHOP_API_URL"] == "https://configured.test/api"


def _config():
    """Enough of a configuration to build a child environment from.

    The company's values now reach the loop from here rather than from
    `os.environ`, which is what lets one deployment name the shop's key once and
    the skills go on calling it `$SHOP_API_KEY`.
    """
    from core.config import (
        Config,
        FeedConfig,
        LokiConfig,
        MatomoConfig,
        ModelConfig,
        QueueConfig,
        ShopConfig,
    )

    return Config(
        model=ModelConfig(name="m", base_url="", api_key=""),
        shop=ShopConfig(
            base_url="https://configured.test/api", api_key="k", timezone="UTC"
        ),
        matomo=MatomoConfig(base_url="https://m.test", token="t", site_id="1"),
        loki=LokiConfig(base_url="http://loki.test"),
        queue=QueueConfig(url="redis://never-passed", namespace="sim"),
        feed=FeedConfig(
            host="erp.test", port=22, user="u", password="p", directory="data"
        ),
    )
