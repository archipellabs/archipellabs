"""Questions that cannot be answered from one system.

The functional tests prove each skill reaches its own system. These prove the
harder thing: that an agent can hold two systems at once, get a figure out of
each, and keep them apart.

**The question goes over the bus**, not into a harness. `ask()` spawns a caller
that does `ctx.call("philip.investigate", ...)` against a running Philip, so the
path under test is the whole one: the action registered under the name callers
use, params validated at the edge, a worker slot claimed, the answer returned
through a reply list, the events published and the run persisted. Reaching into
`harness.investigate()` would exercise the loop and call it end to end.

**The test measures the truth itself, first.** It queries both systems directly,
then asks, then compares. Nothing here grades prose: an assertion on whether an
answer "sounds like it understood" is an assertion about the grader. The only
claims made are that specific numbers came back and that they match what the
systems say.

That also makes the tests self-maintaining. The company keeps trading, so a
hard-coded figure would rot within the hour; a closed window and a fresh
measurement do not.

Marked `e2e`, deselected by default, run with `-m e2e`. Each costs a model turn.
"""

import csv
import datetime
import io
import json
import os
import pathlib
import re
import subprocess
import time
import zoneinfo

import httpx
import pytest

from core.harness import desk
from roles.philip.identity import DESK

AGENTS = pathlib.Path(__file__).resolve().parents[3]
"""The one project root — what the employee is started from."""

pytestmark = pytest.mark.e2e

LAG_HOURS = 2
"""How far back the window ends.

Far enough that nothing is still settling, which is the same reason the lab's
own scenarios use a lagged hour: an answer about a period still in progress ages
between the agent reading it and the test checking it.
"""


@pytest.fixture(scope="session", autouse=True)
def company_is_reachable() -> None:
    if not os.environ.get("SHOP_API_URL"):
        pytest.skip("no company in the environment (source the agent's .env)")


def closed_hour() -> datetime.datetime:
    """The most recent whole hour that ended at least `LAG_HOURS` ago, on the
    shop's clock. The shop writes local time; a window computed in UTC and
    applied to it is out by the offset and returns a plausible wrong answer."""
    shop = zoneinfo.ZoneInfo(os.environ["SHOP_TIMEZONE"])
    now = datetime.datetime.now(shop)
    return now.replace(minute=0, second=0, microsecond=0) - datetime.timedelta(
        hours=LAG_HOURS
    )


def ca() -> str:
    return str(DESK.root / desk.CA_FILE)


def shop_paid_orders(hour: datetime.datetime) -> int:
    """Paid orders the shop recorded in that hour, counted straight."""
    start = hour.strftime("%Y-%m-%d %H:00:00")
    end = hour.strftime("%Y-%m-%d %H:59:59")
    response = httpx.get(
        f"{os.environ['SHOP_API_URL']}/orders",
        params={
            "output_format": "JSON",
            "date": "1",
            "filter[date_add]": f"[{start},{end}]",
            "filter[valid]": "1",
            "display": "[id]",
        },
        auth=(os.environ["SHOP_API_KEY"], ""),
        verify=ca(),
        timeout=30,
    )
    response.raise_for_status()
    return len(response.json().get("orders", []))


def analytics_visits(hour: datetime.datetime) -> int:
    """Visits analytics attributes to that hour, read from the hourly report.

    NOT by composing a segment. This function first did
    `segment=visitServerHour==13` and measured a different hour entirely: the
    hour report's row **labels** are in the site's timezone while the
    `visitStartServerHour` dimension is in UTC, so the row labelled `13` carries
    `segment: visitStartServerHour==18`. The hand-written segment selected
    08:00 local and the test called the agent wrong for reporting the right
    figure.

    The skill documents exactly this and says to copy the row's own segment
    rather than compose one. Reading the row is simpler still.
    """
    response = httpx.post(
        f"{os.environ['MATOMO_URL']}/index.php",
        data={
            "module": "API",
            "method": "VisitTime.getVisitInformationPerServerTime",
            "idSite": os.environ["MATOMO_SITE_ID"],
            "period": "day",
            "date": hour.strftime("%Y-%m-%d"),
            "format": "JSON",
            "token_auth": os.environ["MATOMO_AGENT_TOKEN"],
        },
        verify=ca(),
        timeout=30,
    )
    response.raise_for_status()
    wanted = f"{hour.hour:02d}"
    for row in response.json():
        if str(row["label"]).startswith(wanted):
            return int(row["nb_visits"])
    return 0


def feed_carrier_codes() -> set[str]:
    """The carrier codes the ERP declares, read through the skill's own script."""
    script = DESK.root / "skills/erp-feed/scripts/feed.py"
    done = subprocess.run(
        [str(desk.interpreter()), str(script), "cat", "data/carriers.csv"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    rows = csv.DictReader(io.StringIO(done.stdout))
    return {row["carrier_code"] for row in rows}


@pytest.fixture(scope="session")
def philip_is_serving() -> object:
    """Philip, running as its own process for the whole session.

    Started rather than assumed: a test suite that needs you to remember to
    launch something is a suite that gets run wrong once and mistrusted after.
    """
    # One entry point for every employee, chosen by `AGENT_NAME`. It was
    # `src.app` in this employee's own directory, back when there were seven of
    # those and seven projects to hold them.
    process = subprocess.Popen(
        [str(desk.interpreter()), "-m", "core.main"],
        cwd=str(AGENTS),
        env={**os.environ, "AGENT_NAME": "philip"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"philip exited: {(process.stderr.read() or '')[-400:]}")
        # The action has to be claimable before a call goes out, or the call
        # waits its whole ttl for a service that has not finished booting.
        if _action_stream_exists():
            break
        time.sleep(0.5)
    else:
        process.kill()
        raise TimeoutError("philip did not register philip.investigate within 30s")
    yield process
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _action_stream_exists() -> bool:
    namespace = os.getenv("AGENT_NAMESPACE", "sim")
    prefix = f"{namespace}:" if namespace else ""
    done = subprocess.run(
        ["docker", "exec", "redis", "redis-cli", "EXISTS",
         f"{prefix}act:philip.investigate"],
        capture_output=True, text=True, timeout=10,
    )
    return done.stdout.strip() == "1"


def ask(question: str, _serving: object) -> dict[str, str]:
    """One investigation, requested the way any caller would request it."""
    done = subprocess.run(
        [str(desk.interpreter()), "-m", "tests.philip.e2e.probe", question],
        cwd=str(DESK.root.parent),
        capture_output=True,
        text=True,
        timeout=900,
    )
    line = next(
        (ln for ln in reversed(done.stdout.splitlines()) if ln.startswith("{")), ""
    )
    assert line, f"the probe printed no answer: {done.stderr[-500:]}"
    reply = json.loads(line)
    # `completed` — the envelope has three statuses and "answered" is not
    # one of them; see `core.run`. A failed or crashed run carries an
    # `error` instead of an answer, which is what this is guarding.
    assert reply.get("status") == "completed", reply
    return reply["answer"]


def numbers(text: str) -> set[int]:
    """Every integer in the answer, thousands separators removed.

    Deliberately crude. Asking where in the prose a figure sits would be reading
    the answer's shape, and the shape is the model's to choose.
    """
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text)}


def test_a_light_funnel_crosses_analytics_and_the_shop(
    philip_is_serving: object,
) -> None:
    """One hour, two systems, two figures.

    The smallest question that cannot be answered from one place: analytics
    holds visits, the shop holds paid orders, and there is no shared key between
    them. This does not check that the agent refused to divide one by the other.
    It checks the step before, which is the one that has to work first: that it
    went to both systems and came back with what each actually says.
    """
    hour = closed_hour()
    visits = analytics_visits(hour)
    orders = shop_paid_orders(hour)
    window = hour.strftime("%Y-%m-%d %H:00") + " to " + hour.strftime("%H:59")

    answer = ask(
        f"For {window} {os.environ['SHOP_TIMEZONE']} time, report two figures: "
        "how many visits analytics recorded, and how many valid paid orders the "
        "shop recorded. Put both numbers in the summary field.",
        philip_is_serving,
    )
    reported = numbers(answer["summary"]) | numbers(answer["diagnosis"])

    assert visits in reported, f"analytics said {visits}, answer had {reported}"
    assert orders in reported, f"the shop said {orders}, answer had {reported}"


def test_carriers_cross_the_erp_feed_and_the_shop(philip_is_serving: object) -> None:
    """Reference data, upstream and downstream.

    The feed is what the company intends; the shop is what it currently has. An
    answer needs both, and needs the skill for a system with no HTTP API at all
    alongside the one with the richest.
    """
    codes = feed_carrier_codes()
    assert codes, "the feed declares no carriers; the fixture is wrong, not the agent"

    answer = ask(
        "List the carrier codes the ERP feed declares, and say for each whether "
        "the shop has a matching carrier. Put the codes in the summary field.",
        philip_is_serving,
    )
    summary = f"{answer['summary']} {answer['diagnosis']}".upper()

    for code in codes:
        assert code in summary, f"{code} is in the feed and not in the answer"


def test_the_feed_grain_is_a_carrier_per_country(philip_is_serving: object) -> None:
    """`carrier_id` is not unique per row, and reading it as if it were makes a
    market disappear silently.

    The same UUID appears twice, differing by country. This asks the agent for
    the row count rather than the carrier count, because the two differ and the
    difference is the whole point.
    """
    script = DESK.root / "skills/erp-feed/scripts/feed.py"
    done = subprocess.run(
        [str(desk.interpreter()), str(script), "cat", "data/carriers.csv"],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    rows = list(csv.DictReader(io.StringIO(done.stdout)))
    countries = {row["country"] for row in rows}

    answer = ask(
        "In the ERP feed's carrier file, how many rows are there, and which "
        "countries do they cover? Put the row count and the countries in the "
        "summary field.",
        philip_is_serving,
    )
    summary = f"{answer['summary']} {answer['diagnosis']}".upper()

    assert len(rows) in numbers(summary), f"{len(rows)} rows, answer: {summary[:200]}"
    for country in countries:
        assert country in summary, f"{country} is in the feed and not in the answer"
