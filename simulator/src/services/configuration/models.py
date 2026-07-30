"""The `simulator_setting` entity — one row per overridden setting.

Key/value rather than a column per knob, deliberately. A settings *table* with
typed columns needs a migration every time a knob is added, and a knob that is
only interesting for one afternoon never gets one. The typing lives in
`service.TUNABLES` instead, where it can also reject a bad value before it is
stored — which a column type cannot do for `{"US": 0.75}`.

A missing row means "not overridden", never "zero". That is what lets the static
config stay the single source of defaults.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.db import Base


class SimulatorSetting(Base):
    __tablename__ = "simulator_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
