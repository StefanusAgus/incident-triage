"""Database persistence mapping; validate inputs with IncidentRecord first."""

from datetime import datetime, timezone

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Enum
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, SQLModel

from app.constants import Environment, Severity


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite stores naive UTC; restore timezone information when reading."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Incident(SQLModel, table=True):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("json_valid(tags) AND json_type(tags) = 'array'", name="tags_array"),
    )

    id: str = Field(primary_key=True)
    created_at: datetime = Field(sa_column=Column(UTCDateTime(), nullable=False))
    environment: Environment = Field(sa_column=Column(
        Enum(Environment, values_callable=lambda enum: [item.value for item in enum],
             native_enum=False, create_constraint=True, validate_strings=True),
        nullable=False, index=True,
    ))
    service: str = Field(index=True)
    severity: Severity = Field(sa_column=Column(
        Enum(Severity, native_enum=False, create_constraint=True, validate_strings=True),
        nullable=False, index=True,
    ))
    title: str
    description: str
    resolution_summary: str
    tags: list[str] = Field(sa_column=Column(JSON, nullable=False))
