from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.analytics.definitions import AnalyticsMetricFormat


class AnalyticsMetricQuery(BaseModel):
    metric_key: str
    group_by: str | None = None
    filters: dict[str, object] = Field(default_factory=dict, max_length=100)

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AnalyticsDataPoint(BaseModel):
    value: Decimal
    dimension: str | None = None
    series_key: str | None = None
    series_label: str | None = None

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )

    @field_serializer("value", when_used="json")
    def serialize_value(self, value: Decimal) -> str:
        return format(value, "f")


class AnalyticsMetricResult(BaseModel):
    metric_key: str
    format: AnalyticsMetricFormat
    group_by: str | None = None
    unit: str | None = None
    points: tuple[AnalyticsDataPoint, ...]

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        revalidate_instances="always",
    )
