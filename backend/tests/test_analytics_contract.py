from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.analytics.definitions import (
    AnalyticsDimensionDefinition,
    AnalyticsFilterDefinition,
    AnalyticsFilterValueType,
    AnalyticsMetricDefinition,
    AnalyticsMetricFormat,
)
from app.core.analytics.provider import (
    AnalyticsProviderContext,
    ValidatedAnalyticsMetricQuery,
)
from app.core.analytics.schemas import (
    AnalyticsDataPoint,
    AnalyticsMetricQuery,
    AnalyticsMetricResult,
)
from app.core.analytics.validation import (
    AnalyticsQueryValidationError,
    AnalyticsResultValidationError,
    InvalidAnalyticsDefinitionError,
    validate_metric_query,
    validate_metric_result,
)
from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)
from app.core.module_registry.registry import ModuleRegistry, production_module_registry
from tests.analytics_fakes import OperationsAnalyticsProvider


class StubProvider:
    def __init__(
        self,
        *,
        module_key: str = "operations_test",
        metrics: tuple[AnalyticsMetricDefinition, ...],
    ) -> None:
        self.module_key = module_key
        self._metrics = metrics

    def metrics(self) -> tuple[AnalyticsMetricDefinition, ...]:
        return self._metrics

    def query(
        self,
        *,
        session: Session,
        context: AnalyticsProviderContext,
        query: ValidatedAnalyticsMetricQuery,
    ) -> AnalyticsMetricResult:
        del session, context
        return AnalyticsMetricResult(
            metric_key=query.metric_key,
            format=self._metrics[0].format,
            group_by=query.group_by,
            points=(AnalyticsDataPoint(value=Decimal("1")),),
        )


class MetricsOnlyProvider:
    module_key = "operations_test"

    def metrics(self) -> tuple[AnalyticsMetricDefinition, ...]:
        return (metric(),)


def permission(
    module_key: str = "operations_test",
    resource: str = "record",
) -> PermissionDefinition:
    return PermissionDefinition(
        key=f"{module_key}.{resource}.read",
        resource=resource,
        action="read",
    )


def metric(**changes: object) -> AnalyticsMetricDefinition:
    values: dict[str, object] = {
        "key": "operations_test.record_count",
        "name_key": "modules.operations_test.analytics.record_count",
        "format": AnalyticsMetricFormat.NUMBER,
        "required_permission": "operations_test.record.read",
    }
    values.update(changes)
    return AnalyticsMetricDefinition(**values)  # type: ignore[arg-type]


def module_with_provider(provider: object) -> ModuleDefinition:
    return ModuleDefinition(
        key="operations_test",
        name_key="modules.operations_test.name",
        permissions=(permission(),),
        analytics_provider=provider,  # type: ignore[arg-type]
    )


def test_valid_provider_and_module_without_provider_are_supported() -> None:
    provider = OperationsAnalyticsProvider()
    with_provider = module_with_provider(provider)
    without_provider = ModuleDefinition(
        key="plain_test",
        name_key="modules.plain_test.name",
        permissions=(permission("plain_test"),),
    )

    registry = ModuleRegistry([with_provider, without_provider])

    assert registry.get("operations_test") is with_provider
    assert registry.get("plain_test") is without_provider
    assert without_provider.analytics_provider is None
    assert registry.get_analytics_metric("operations_test.record_count") is not None
    assert registry.list_analytics_metrics("plain_test") == ()


def test_registry_uses_the_validated_metric_snapshot() -> None:
    original = metric()
    provider = StubProvider(metrics=(original,))
    registry = ModuleRegistry([module_with_provider(provider)])

    provider._metrics = (metric(key="operations_test.changed"),)

    assert registry.get_analytics_metric(original.key) is original
    assert registry.get_analytics_metric("operations_test.changed") is None
    assert registry.list_analytics_metrics("operations_test") == (original,)


def test_provider_missing_query_contract_is_rejected() -> None:
    with pytest.raises(InvalidAnalyticsDefinitionError):
        ModuleRegistry([module_with_provider(MetricsOnlyProvider())])


@pytest.mark.parametrize(
    "provider",
    [
        StubProvider(module_key="other_test", metrics=(metric(),)),
        StubProvider(metrics=(metric(key="record_count"),)),
        StubProvider(metrics=(metric(key="operations_test.RecordCount"),)),
        StubProvider(metrics=(metric(key="other_test.record_count"),)),
        StubProvider(metrics=(metric(), metric())),
        StubProvider(metrics=(metric(required_permission="operations_test.missing.read"),)),
        StubProvider(metrics=(metric(required_permission="other_test.record.read"),)),
        StubProvider(
            metrics=(
                metric(
                    dimensions=(
                        AnalyticsDimensionDefinition("month"),
                        AnalyticsDimensionDefinition("month"),
                    )
                ),
            )
        ),
        StubProvider(
            metrics=(
                metric(dimensions=(AnalyticsDimensionDefinition("Month"),)),
            )
        ),
        StubProvider(
            metrics=(
                metric(
                    filters=(
                        AnalyticsFilterDefinition(
                            "date_from", AnalyticsFilterValueType.DATE
                        ),
                        AnalyticsFilterDefinition(
                            "date_from", AnalyticsFilterValueType.DATE
                        ),
                    )
                ),
            )
        ),
        StubProvider(
            metrics=(
                metric(
                    filters=(
                        AnalyticsFilterDefinition(
                            "DateFrom", AnalyticsFilterValueType.DATE
                        ),
                    )
                ),
            )
        ),
        StubProvider(
            metrics=(
                metric(
                    filters=(
                        AnalyticsFilterDefinition("filter", "json"),  # type: ignore[arg-type]
                    )
                ),
            )
        ),
        StubProvider(metrics=(metric(format="chart"),)),
    ],
)
def test_invalid_provider_definitions_are_rejected(provider: StubProvider) -> None:
    with pytest.raises(InvalidAnalyticsDefinitionError):
        ModuleRegistry([module_with_provider(provider)])


@pytest.mark.parametrize("format", list(AnalyticsMetricFormat))
def test_all_supported_metric_formats_register(
    format: AnalyticsMetricFormat,
) -> None:
    ModuleRegistry([module_with_provider(StubProvider(metrics=(metric(format=format),)))])


def filter_metric() -> AnalyticsMetricDefinition:
    return metric(
        dimensions=(AnalyticsDimensionDefinition("month"),),
        filters=(
            AnalyticsFilterDefinition(
                "required_date", AnalyticsFilterValueType.DATE, required=True
            ),
            AnalyticsFilterDefinition("uuid_value", AnalyticsFilterValueType.UUID),
            AnalyticsFilterDefinition("integer_value", AnalyticsFilterValueType.INTEGER),
            AnalyticsFilterDefinition("number_value", AnalyticsFilterValueType.NUMBER),
            AnalyticsFilterDefinition("boolean_value", AnalyticsFilterValueType.BOOLEAN),
            AnalyticsFilterDefinition("string_value", AnalyticsFilterValueType.STRING),
            AnalyticsFilterDefinition("datetime_value", AnalyticsFilterValueType.DATETIME),
        ),
    )


def test_query_validation_accepts_scalar_grouped_and_normalized_filters() -> None:
    identifier = uuid4()
    query = AnalyticsMetricQuery(
        metric_key="operations_test.record_count",
        group_by="month",
        filters={
            "required_date": "2026-08-24",
            "uuid_value": str(identifier),
            "integer_value": 7,
            "number_value": 12.5,
            "boolean_value": True,
            "string_value": "active",
            "datetime_value": "2026-08-24T12:30:00+00:00",
        },
    )

    validated = validate_metric_query(filter_metric(), query)
    scalar = validate_metric_query(
        filter_metric(),
        AnalyticsMetricQuery(
            metric_key="operations_test.record_count",
            filters={"required_date": date(2026, 8, 24)},
        ),
    )

    assert validated.group_by == "month"
    assert validated.filters["required_date"] == date(2026, 8, 24)
    assert validated.filters["uuid_value"] == identifier
    assert validated.filters["number_value"] == Decimal("12.5")
    assert validated.filters["datetime_value"] == datetime.fromisoformat(
        "2026-08-24T12:30:00+00:00"
    )
    assert scalar.group_by is None


@pytest.mark.parametrize(
    ("group_by", "filters"),
    [
        ("category", {"required_date": "2026-08-24"}),
        (None, {"unknown": "value", "required_date": "2026-08-24"}),
        (None, {}),
        (None, {"required_date": "2026-08-24", "uuid_value": "not-a-uuid"}),
        (None, {"required_date": "not-a-date"}),
        (None, {"required_date": "2026-08-24", "number_value": "12.5"}),
        (None, {"required_date": "2026-08-24", "integer_value": True}),
        (None, {"required_date": "2026-08-24", "boolean_value": "true"}),
    ],
)
def test_invalid_query_shape_or_filters_are_rejected(
    group_by: str | None, filters: dict[str, object]
) -> None:
    query = AnalyticsMetricQuery(
        metric_key="operations_test.record_count",
        group_by=group_by,
        filters=filters,
    )
    with pytest.raises(AnalyticsQueryValidationError):
        validate_metric_query(filter_metric(), query)


@pytest.mark.parametrize(
    "extra",
    [
        {"organization_id": str(uuid4())},
        {"sql": "select 1"},
        {"table": "users"},
        {"column": "email"},
    ],
)
def test_query_schema_forbids_tenant_and_sql_metadata(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AnalyticsMetricQuery.model_validate(
            {"metric_key": "operations_test.record_count", **extra}
        )


def result_metric(format: AnalyticsMetricFormat) -> AnalyticsMetricDefinition:
    return metric(
        format=format,
        dimensions=(AnalyticsDimensionDefinition("month"),),
    )


def validated_query(group_by: str | None = None) -> ValidatedAnalyticsMetricQuery:
    return validate_metric_query(
        result_metric(AnalyticsMetricFormat.NUMBER),
        AnalyticsMetricQuery(
            metric_key="operations_test.record_count",
            group_by=group_by,
        ),
    )


@pytest.mark.parametrize(
    ("format", "unit", "value"),
    [
        (AnalyticsMetricFormat.NUMBER, None, Decimal("12")),
        (AnalyticsMetricFormat.CURRENCY, "BRL", Decimal("12.50")),
        (AnalyticsMetricFormat.PERCENTAGE, None, Decimal("0.25")),
        (AnalyticsMetricFormat.DURATION, "minutes", Decimal("90")),
    ],
)
def test_valid_scalar_result_formats(
    format: AnalyticsMetricFormat,
    unit: str | None,
    value: Decimal,
) -> None:
    definition = result_metric(format)
    query = validate_metric_query(
        definition,
        AnalyticsMetricQuery(metric_key=definition.key),
    )
    result = AnalyticsMetricResult(
        metric_key=definition.key,
        format=format,
        unit=unit,
        points=(AnalyticsDataPoint(value=value),),
    )

    assert validate_metric_result(metric=definition, query=query, result=result) == result


def test_valid_grouped_result_is_visualization_agnostic() -> None:
    definition = result_metric(AnalyticsMetricFormat.NUMBER)
    query = validate_metric_query(
        definition,
        AnalyticsMetricQuery(metric_key=definition.key, group_by="month"),
    )
    result = AnalyticsMetricResult(
        metric_key=definition.key,
        format=definition.format,
        group_by="month",
        points=(
            AnalyticsDataPoint(dimension="2026-01", value=Decimal("4")),
            AnalyticsDataPoint(dimension="2026-02", value=Decimal("7")),
        ),
    )

    assert validate_metric_result(metric=definition, query=query, result=result) == result
    assert "chart" not in AnalyticsMetricResult.model_fields
    assert result.model_dump(mode="json")["points"][0]["value"] == "4"


@pytest.mark.parametrize(
    "result",
    [
        AnalyticsMetricResult(
            metric_key="operations_test.wrong",
            format=AnalyticsMetricFormat.NUMBER,
            points=(AnalyticsDataPoint(value=Decimal("1")),),
        ),
        AnalyticsMetricResult(
            metric_key="operations_test.record_count",
            format=AnalyticsMetricFormat.CURRENCY,
            unit="BRL",
            points=(AnalyticsDataPoint(value=Decimal("1")),),
        ),
        AnalyticsMetricResult(
            metric_key="operations_test.record_count",
            format=AnalyticsMetricFormat.NUMBER,
            group_by="month",
            points=(AnalyticsDataPoint(dimension="2026-01", value=Decimal("1")),),
        ),
        AnalyticsMetricResult(
            metric_key="operations_test.record_count",
            format=AnalyticsMetricFormat.NUMBER,
            points=(
                AnalyticsDataPoint(dimension="unexpected", value=Decimal("1")),
            ),
        ),
    ],
)
def test_provider_contract_mismatches_are_rejected(
    result: AnalyticsMetricResult,
) -> None:
    with pytest.raises(AnalyticsResultValidationError):
        validate_metric_result(
            metric=result_metric(AnalyticsMetricFormat.NUMBER),
            query=validated_query(),
            result=result,
        )


@pytest.mark.parametrize(
    ("format", "unit", "value"),
    [
        (AnalyticsMetricFormat.CURRENCY, None, Decimal("1")),
        (AnalyticsMetricFormat.CURRENCY, "brl", Decimal("1")),
        (AnalyticsMetricFormat.DURATION, "milliseconds", Decimal("1")),
        (AnalyticsMetricFormat.PERCENTAGE, None, Decimal("25")),
        (AnalyticsMetricFormat.NUMBER, "items", Decimal("1")),
    ],
)
def test_invalid_units_and_percentage_scale_are_rejected(
    format: AnalyticsMetricFormat,
    unit: str | None,
    value: Decimal,
) -> None:
    definition = result_metric(format)
    query = validate_metric_query(
        definition,
        AnalyticsMetricQuery(metric_key=definition.key),
    )
    result = AnalyticsMetricResult(
        metric_key=definition.key,
        format=format,
        unit=unit,
        points=(AnalyticsDataPoint(value=value),),
    )
    with pytest.raises(AnalyticsResultValidationError):
        validate_metric_result(metric=definition, query=query, result=result)


def test_malformed_data_point_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AnalyticsDataPoint.model_validate({"dimension": "2026-01"})

    malformed = AnalyticsMetricResult.model_construct(
        metric_key="operations_test.record_count",
        format=AnalyticsMetricFormat.NUMBER,
        points=({},),
    )
    with pytest.raises(AnalyticsResultValidationError):
        validate_metric_result(
            metric=result_metric(AnalyticsMetricFormat.NUMBER),
            query=validated_query(),
            result=malformed,
        )


def test_production_registry_has_no_analytics_provider() -> None:
    assert production_module_registry.list() == ()
    assert all(
        module.analytics_provider is None
        for module in production_module_registry.list()
    )
