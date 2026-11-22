"""Validation contracts shared by dataset loading and future API boundaries."""

from datetime import datetime, timezone
from typing import Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.constants import (
    DEFAULT_SEARCH_LIMIT,
    MAX_FILTER_TAGS,
    MAX_FILTER_VALUE_LENGTH,
    MAX_SEARCH_LIMIT,
    MAX_SEARCH_QUERY_LENGTH,
    Environment,
    Severity,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FilterValue = Annotated[str, StringConstraints(
    strip_whitespace=True, min_length=1, max_length=MAX_FILTER_VALUE_LENGTH,
)]


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

    @model_validator(mode="after")
    def require_unique_ids(self) -> "IncidentDataset":
        seen = set()
        for record in self.root:
            if record.id in seen:
                raise ValueError(f"Duplicate incident ID: {record.id}")
            seen.add(record.id)
        return self


class IngestResult(BaseModel):
    """Counts of newly inserted, unchanged, and updated incident records."""

    ingested: int = 0
    skipped: int = 0
    updated: int = 0


class IncidentFilters(BaseModel):
    """AND across filters; tags require every exact, case-sensitive value."""

    model_config = ConfigDict(extra="forbid")

    environment: Environment | None = None
    service: FilterValue | None = None
    severity: Severity | None = None
    tags: list[FilterValue] = Field(
        default_factory=list, max_length=MAX_FILTER_TAGS,
        description="Repeat tags to require all exact, case-sensitive tag values.",
    )


class SearchParams(IncidentFilters):
    q: str = Field(
        min_length=1, max_length=MAX_SEARCH_QUERY_LENGTH,
        description="Plain text keywords; common question words are ignored, remaining words are matched with OR.",
    )
    limit: int = Field(default=DEFAULT_SEARCH_LIMIT, ge=1, le=MAX_SEARCH_LIMIT)

    @field_validator("q")
    @classmethod
    def require_search_terms(cls, value: str) -> str:
        value = value.strip()
        if not any(character.isalnum() for character in value):
            raise ValueError("Search query must contain at least one letter or number")
        return value


class SearchResult(BaseModel):
    id: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
