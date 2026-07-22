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


settings = Settings()
