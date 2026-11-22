"""Validation contracts shared by dataset loading and future API boundaries."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    RootModel,
    StringConstraints,
    field_validator,
)

from app.constants import Environment, Severity

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class IncidentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: NonEmptyString
    created_at: AwareDatetime
    environment: Environment
    service: NonEmptyString
    severity: Severity
    title: NonEmptyString
    description: NonEmptyString
    resolution_summary: NonEmptyString
    tags: list[NonEmptyString]

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class IncidentDataset(RootModel[list[IncidentRecord]]):
    """A JSON array of validated incidents; sample count is configurable."""
