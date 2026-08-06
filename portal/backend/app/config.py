from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Read-only connection to the simulator's activity database. Prefers DATABASE_URL,
    # then SIMULATORDB_URL (the var the simulator stack already defines, so the portal
    # needs no extra config there), else the localhost default for a local run.
    database_url: str = Field(
        default="postgresql+psycopg://simulator:changeme_demo@localhost:5432/simulator",
        validation_alias=AliasChoices("DATABASE_URL", "SIMULATORDB_URL"),
    )

    # The agent bus. Giving the portal Redis reverses the boundary the compose
    # file states — it used to see only the activity database — and that is a
    # deliberate reversal, not an oversight: the ask page exists to reach the
    # employees, and they live on the bus. The namespace must match theirs or a
    # call travels a keyspace nobody is listening on and waits out its ttl
    # against nobody.
    #
    # **`AGENT_*` first, because that is what the employees read.** One bus had
    # three spellings for its namespace — `AGENT_NAMESPACE` here, `REDIS_NAMESPACE`
    # there, a bare `NAMESPACE` in the simulator — and they agreed only because
    # all three defaulted to `sim`. Setting one of them would have moved one
    # process off the bus and left the others behind, which does not fail: a call
    # simply waits out its ttl against a keyspace nobody serves. The old names
    # stay as a fallback so a deployment that already sets them keeps working.
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("AGENT_REDIS_URL", "REDIS_URL"),
    )
    redis_namespace: str = Field(
        default="sim",
        validation_alias=AliasChoices("AGENT_NAMESPACE", "REDIS_NAMESPACE"),
    )

    # The password for the two pages that are not read-only: /ask, which spends
    # money on a model, and /settings, which changes how the simulated company
    # behaves. Unset means those pages are closed to everyone rather than open to
    # everyone — see app/auth.py.
    portal_password: str = Field(
        default="", validation_alias=AliasChoices("PORTAL_PASSWORD")
    )
    # Whether those two pages ask at all. **True by default**, and switching it
    # off is a deliberate line in a deployment's own file rather than something
    # a missing variable does for you: the interesting failure here is a stack
    # that meant to be locked and quietly was not.
    #
    # Off is for a local machine, where the shop is on localhost and typing a
    # password to watch a mock investigation is friction with nothing behind it.
    auth_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("PORTAL_AUTH_ENABLED")
    )
    # Signs the session cookie. Unset means a fresh key per process, so restarting
    # the portal signs everyone out; set it to keep sessions across a restart, and
    # to let more than one worker verify each other's cookies.
    session_secret: str = Field(
        default="", validation_alias=AliasChoices("PORTAL_SESSION_SECRET")
    )
    # Send the session cookie only over TLS. False by default because local
    # development is http on localhost, where a Secure cookie is dropped without
    # a word and the login looks like it silently failed.
    cookie_secure: bool = Field(
        default=False, validation_alias=AliasChoices("PORTAL_COOKIE_SECURE")
    )

    # Where the log store answers, for the one component that exposes no endpoint
    # of its own: the integration runtime's liveness is visible only in the lines
    # it writes. Internal name on the shared network.
    loki_url: str = Field(
        default="http://loki:3100", validation_alias=AliasChoices("LOKI_URL")
    )

    # Public URLs the cartography cards open (the visitor's browser follows them).
    # Default to the local stack; a public deployment overrides these with its own
    # domains via STOREFRONT_URL / BACKOFFICE_URL / ANALYTICS_URL.
    #
    # **Each service at the root of its own name**, which is what the gateway
    # serves. These read `https://localhost/`, `/admin-dev/` and `/stats/` until
    # the day the gateway stopped carrying paths — `nginx.conf` says of the last
    # one that "the proxy_pass that /stats/ needed is simply gone", and no vhost
    # answers to `localhost` at all, so the default server returned 421 and three
    # of the four cards opened an error. `dashboards_url` was updated at the
    # time; these three were not, and nothing failed loudly enough to say so.
    storefront_url: str = "https://shop.archipellabs.test/"
    backoffice_url: str = "https://shop.archipellabs.test/admin-dev/"
    analytics_url: str = "https://tracking.archipellabs.test/"
    dashboards_url: str = "https://grafana.archipellabs.test/"


settings = Settings()
