from dataclasses import dataclass
from enum import StrEnum


class AnalyticsMetricFormat(StrEnum):
    NUMBER = "number"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    DURATION = "duration"


class AnalyticsFilterValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    UUID = "uuid"


class AnalyticsDurationUnit(StrEnum):
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    DAYS = "days"


@dataclass(frozen=True, slots=True)
class AnalyticsDimensionDefinition:
    key: str
    name_key: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsFilterDefinition:
    key: str
    value_type: AnalyticsFilterValueType
    required: bool = False
    name_key: str | None = None


@dataclass(frozen=True, slots=True)
class AnalyticsMetricDefinition:
    key: str
    name_key: str
    format: AnalyticsMetricFormat
    required_permission: str
    dimensions: tuple[AnalyticsDimensionDefinition, ...] = ()
    filters: tuple[AnalyticsFilterDefinition, ...] = ()
    description_key: str | None = None
