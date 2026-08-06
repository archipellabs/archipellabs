"""What is Blair's alone, now that the loop is not.

The driver, the record and the envelope moved to `core` and are checked
there. What stays here is who this employee is on the bus and which loop it is
built on.
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
from roles.blair.identity import AGENT, IDENTITY


def _config() -> Config:
    return Config(
        ModelConfig("m", "", ""),
        ShopConfig("", "", "UTC"),
        MatomoConfig("", "", "1"),
        LokiConfig(""),
        QueueConfig("", ""),
        FeedConfig("", 22, "", "", ""),
    )


def test_the_identity_runs_on_the_same_loop_as_angel():
    """Blair and Angel differ by their tools and nothing else; a second loop
    here would make every comparison between them a comparison of two things."""
    assert IDENTITY.name == AGENT == "blair"
    assert isinstance(IDENTITY.build(_config()), PydanticAiHarness)


def test_the_bus_routes_this_employee_s_own_action():
    """Two employees serving one action name would split the tickets between
    themselves, silently, each looking like it was working normally."""
    service = serve(IDENTITY)

    assert service.name == "blair"
    assert [action.name for action in service.consumers] == ["blair.investigate"]
