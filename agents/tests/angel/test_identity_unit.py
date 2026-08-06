"""What is Angel's alone, now that the loop is not.

The driver, the record and the envelope moved to `core` and are checked
there. What stays here is who this employee is on the bus and which loop it is
built on — the two things `test_topics_unit` and `test_service_unit` used to
cover with copies of code that no longer exists.
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
from core.harness.pydantic_ai import PydanticAiHarness
from core.service import serve
from roles.angel.identity import AGENT, IDENTITY


def _config() -> Config:
    return Config(
        model=ModelConfig(name="m", base_url="", api_key=""),
        shop=ShopConfig(base_url="", api_key="", timezone="UTC"),
        matomo=MatomoConfig(base_url="", token="", site_id="1"),
        loki=LokiConfig(base_url=""),
        queue=QueueConfig(url="", namespace=""),
        feed=FeedConfig(host="", port=22, user="", password="", directory=""),
    )


def test_the_identity_runs_on_the_loop_written_in_python():
    """Angel and Dana hold the same tools; the loop is the whole difference."""
    assert IDENTITY.name == AGENT == "angel"
    assert isinstance(IDENTITY.build(_config()), PydanticAiHarness)


def test_the_bus_routes_this_employee_s_own_action():
    """An action has exactly one correct executant, and the runtime gives every
    consumer of a name one shared group — so two containers serving
    `analyst.investigate` would split the tickets between themselves, silently,
    each looking like it was working normally. The name is the only defence."""
    service = serve(IDENTITY)

    assert service.name == "angel"
    assert [action.name for action in service.consumers] == ["angel.investigate"]
