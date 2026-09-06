from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
    )


class SourceStatus(StrEnum):
    LIVE = "LIVE"
    STALE = "STALE"
    OFFLINE = "OFFLINE"
