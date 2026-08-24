import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from uuid import UUID

from pydantic import ValidationError

from app.core.analytics.definitions import (
    AnalyticsDimensionDefinition,
    AnalyticsDurationUnit,
    AnalyticsFilterDefinition,
    AnalyticsFilterValueType,
    AnalyticsMetricDefinition,
    AnalyticsMetricFormat,
)
from app.core.analytics.provider import (
    AnalyticsFilterValue,
    AnalyticsProvider,
    ValidatedAnalyticsMetricQuery,
)
from app.core.analytics.schemas import AnalyticsMetricQuery, AnalyticsMetricResult

IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
METRIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")


class InvalidAnalyticsDefinitionError(ValueError):
    pass


class AnalyticsQueryValidationError(ValueError):
    pass


class AnalyticsResultValidationError(ValueError):
    pass


def validate_provider_definition(
    *,
    module_key: str,
    permission_keys: set[str],
    provider: AnalyticsProvider,
) -> tuple[AnalyticsMetricDefinition, ...]:
    if getattr(provider, "module_key", None) != module_key:
        raise InvalidAnalyticsDefinitionError(
            f"Analytics provider module must be {module_key}"
        )
    if not callable(getattr(provider, "metrics", None)) or not callable(
        getattr(provider, "query", None)
    ):
        raise InvalidAnalyticsDefinitionError(
            "Analytics provider must implement metrics and query"
        )
    metrics = provider.metrics()
    if not isinstance(metrics, tuple):
        raise InvalidAnalyticsDefinitionError("Analytics provider metrics must be a tuple")

    metric_keys: set[str] = set()
    for metric in metrics:
        _validate_metric_definition(
            module_key=module_key,
            permission_keys=permission_keys,
            metric=metric,
        )
        if metric.key in metric_keys:
            raise InvalidAnalyticsDefinitionError(
                f"Duplicate Analytics metric key: {metric.key}"
            )
        metric_keys.add(metric.key)
    return metrics


def _validate_metric_definition(
    *,
    module_key: str,
    permission_keys: set[str],
    metric: AnalyticsMetricDefinition,
) -> None:
    if not isinstance(metric, AnalyticsMetricDefinition):
        raise InvalidAnalyticsDefinitionError("Provider returned an invalid metric definition")
    if METRIC_KEY_PATTERN.fullmatch(metric.key) is None:
        raise InvalidAnalyticsDefinitionError(f"Invalid Analytics metric key: {metric.key}")
    if not metric.key.startswith(f"{module_key}."):
        raise InvalidAnalyticsDefinitionError(
            f"Analytics metric must use module namespace {module_key}: {metric.key}"
        )
    if type(metric.name_key) is not str or not metric.name_key.strip():
        raise InvalidAnalyticsDefinitionError("Analytics metric name key is required")
    if metric.description_key is not None and not metric.description_key.strip():
        raise InvalidAnalyticsDefinitionError("Analytics description key cannot be blank")
    if not isinstance(metric.format, AnalyticsMetricFormat):
        raise InvalidAnalyticsDefinitionError(
            f"Unsupported Analytics metric format: {metric.format}"
        )
    if (
        metric.required_permission not in permission_keys
        or not metric.required_permission.startswith(f"{module_key}.")
    ):
        raise InvalidAnalyticsDefinitionError(
            f"Invalid Analytics metric permission: {metric.required_permission}"
        )

    dimension_keys: set[str] = set()
    for dimension in metric.dimensions:
        if not isinstance(dimension, AnalyticsDimensionDefinition):
            raise InvalidAnalyticsDefinitionError(
                "Metric contains an invalid Analytics dimension definition"
            )
        if IDENTIFIER_PATTERN.fullmatch(dimension.key) is None:
            raise InvalidAnalyticsDefinitionError(
                f"Invalid Analytics dimension key: {dimension.key}"
            )
        if dimension.key in dimension_keys:
            raise InvalidAnalyticsDefinitionError(
                f"Duplicate Analytics dimension key: {dimension.key}"
            )
        if dimension.name_key is not None and not dimension.name_key.strip():
            raise InvalidAnalyticsDefinitionError("Analytics dimension name key cannot be blank")
        dimension_keys.add(dimension.key)

    filter_keys: set[str] = set()
    for filter_definition in metric.filters:
        _validate_filter_definition(filter_definition)
        if filter_definition.key in filter_keys:
            raise InvalidAnalyticsDefinitionError(
                f"Duplicate Analytics filter key: {filter_definition.key}"
            )
        filter_keys.add(filter_definition.key)


def _validate_filter_definition(filter_definition: AnalyticsFilterDefinition) -> None:
    if not isinstance(filter_definition, AnalyticsFilterDefinition):
        raise InvalidAnalyticsDefinitionError(
            "Metric contains an invalid Analytics filter definition"
        )
    if IDENTIFIER_PATTERN.fullmatch(filter_definition.key) is None:
        raise InvalidAnalyticsDefinitionError(
            f"Invalid Analytics filter key: {filter_definition.key}"
        )
    if not isinstance(filter_definition.value_type, AnalyticsFilterValueType):
        raise InvalidAnalyticsDefinitionError(
            f"Unsupported Analytics filter type: {filter_definition.value_type}"
        )
    if type(filter_definition.required) is not bool:
        raise InvalidAnalyticsDefinitionError("Analytics filter required must be boolean")
    if filter_definition.name_key is not None and not filter_definition.name_key.strip():
        raise InvalidAnalyticsDefinitionError("Analytics filter name key cannot be blank")


def validate_metric_query(
    metric: AnalyticsMetricDefinition,
    query: AnalyticsMetricQuery,
) -> ValidatedAnalyticsMetricQuery:
    if query.metric_key != metric.key:
        raise AnalyticsQueryValidationError("Query metric does not match definition")
    dimension_keys = {dimension.key for dimension in metric.dimensions}
    if query.group_by is not None and query.group_by not in dimension_keys:
        raise AnalyticsQueryValidationError(
            f"Unsupported Analytics group_by: {query.group_by}"
        )

    definitions = {definition.key: definition for definition in metric.filters}
    unknown_filters = set(query.filters).difference(definitions)
    if unknown_filters:
        raise AnalyticsQueryValidationError(
            f"Unknown Analytics filter: {sorted(unknown_filters)[0]}"
        )
    missing_filters = {
        key
        for key, definition in definitions.items()
        if definition.required and key not in query.filters
    }
    if missing_filters:
        raise AnalyticsQueryValidationError(
            f"Missing required Analytics filter: {sorted(missing_filters)[0]}"
        )

    normalized: dict[str, AnalyticsFilterValue] = {}
    for key in sorted(query.filters):
        normalized[key] = _normalize_filter_value(definitions[key], query.filters[key])
    return ValidatedAnalyticsMetricQuery(
        metric_key=query.metric_key,
        group_by=query.group_by,
        filters=MappingProxyType(normalized),
    )


def _normalize_filter_value(
    definition: AnalyticsFilterDefinition, value: object
) -> AnalyticsFilterValue:
    try:
        match definition.value_type:
            case AnalyticsFilterValueType.STRING:
                if type(value) is not str:
                    raise ValueError
                return value
            case AnalyticsFilterValueType.INTEGER:
                if type(value) is not int:
                    raise ValueError
                return value
            case AnalyticsFilterValueType.NUMBER:
                if type(value) not in {int, float, Decimal}:
                    raise ValueError
                normalized = Decimal(str(value))
                if not normalized.is_finite():
                    raise ValueError
                return normalized
            case AnalyticsFilterValueType.BOOLEAN:
                if type(value) is not bool:
                    raise ValueError
                return value
            case AnalyticsFilterValueType.DATE:
                if type(value) is date:
                    return value
                if type(value) is not str:
                    raise ValueError
                return date.fromisoformat(value)
            case AnalyticsFilterValueType.DATETIME:
                if type(value) is datetime:
                    return value
                if type(value) is not str:
                    raise ValueError
                return datetime.fromisoformat(value)
            case AnalyticsFilterValueType.UUID:
                if type(value) is UUID:
                    return value
                if type(value) is not str:
                    raise ValueError
                return UUID(value)
    except (InvalidOperation, ValueError) as error:
        raise AnalyticsQueryValidationError(
            f"Invalid value for Analytics filter {definition.key}"
        ) from error
    raise AnalyticsQueryValidationError(
        f"Unsupported Analytics filter type: {definition.value_type}"
    )


def validate_metric_result(
    *,
    metric: AnalyticsMetricDefinition,
    query: ValidatedAnalyticsMetricQuery,
    result: AnalyticsMetricResult,
) -> AnalyticsMetricResult:
    try:
        validated = AnalyticsMetricResult.model_validate(result)
    except ValidationError as error:
        raise AnalyticsResultValidationError("Provider returned a malformed result") from error

    if validated.metric_key != metric.key:
        raise AnalyticsResultValidationError("Provider returned the wrong metric key")
    if validated.format is not metric.format:
        raise AnalyticsResultValidationError("Provider returned the wrong metric format")
    if validated.group_by != query.group_by:
        raise AnalyticsResultValidationError("Provider returned the wrong group_by")
    if validated.group_by is None:
        if len(validated.points) != 1 or validated.points[0].dimension is not None:
            raise AnalyticsResultValidationError(
                "Scalar Analytics result must contain one dimensionless point"
            )
    elif any(point.dimension is None for point in validated.points):
        raise AnalyticsResultValidationError(
            "Grouped Analytics result points require a dimension"
        )

    for point in validated.points:
        if not point.value.is_finite():
            raise AnalyticsResultValidationError("Analytics values must be finite")
        if point.series_label is not None and point.series_key is None:
            raise AnalyticsResultValidationError("Series label requires a series key")
        if metric.format is AnalyticsMetricFormat.PERCENTAGE and not (
            Decimal("0") <= point.value <= Decimal("1")
        ):
            raise AnalyticsResultValidationError(
                "Percentage Analytics values must use the 0-to-1 convention"
            )

    _validate_result_unit(metric.format, validated.unit)
    return validated


def _validate_result_unit(format: AnalyticsMetricFormat, unit: str | None) -> None:
    if format is AnalyticsMetricFormat.CURRENCY:
        if unit is None or CURRENCY_CODE_PATTERN.fullmatch(unit) is None:
            raise AnalyticsResultValidationError(
                "Currency Analytics results require an uppercase three-letter unit"
            )
    elif format is AnalyticsMetricFormat.DURATION:
        if unit not in {item.value for item in AnalyticsDurationUnit}:
            raise AnalyticsResultValidationError(
                "Duration Analytics results require a supported unit"
            )
    elif unit is not None:
        raise AnalyticsResultValidationError(
            "Only currency and duration Analytics results may declare a unit"
        )
