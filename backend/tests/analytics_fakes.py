from datetime import date
from decimal import Decimal

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
from app.core.analytics.schemas import AnalyticsDataPoint, AnalyticsMetricResult


class OperationsAnalyticsProvider:
    module_key = "operations_test"

    def __init__(self) -> None:
        self.calls = 0
        self.last_context: AnalyticsProviderContext | None = None
        self.last_query: ValidatedAnalyticsMetricQuery | None = None
        self.failure: Exception | None = None
        self.result_override: AnalyticsMetricResult | None = None

    def metrics(self) -> tuple[AnalyticsMetricDefinition, ...]:
        return (
            AnalyticsMetricDefinition(
                key="operations_test.record_count",
                name_key="modules.operations_test.analytics.record_count",
                format=AnalyticsMetricFormat.NUMBER,
                required_permission="operations_test.record.read",
                dimensions=(AnalyticsDimensionDefinition(key="month"),),
                filters=(
                    AnalyticsFilterDefinition(
                        key="date_from",
                        value_type=AnalyticsFilterValueType.DATE,
                        required=True,
                    ),
                    AnalyticsFilterDefinition(
                        key="date_to",
                        value_type=AnalyticsFilterValueType.DATE,
                    ),
                    AnalyticsFilterDefinition(
                        key="active",
                        value_type=AnalyticsFilterValueType.BOOLEAN,
                    ),
                ),
            ),
        )

    def query(
        self,
        *,
        session: Session,
        context: AnalyticsProviderContext,
        query: ValidatedAnalyticsMetricQuery,
    ) -> AnalyticsMetricResult:
        del session
        self.calls += 1
        self.last_context = context
        self.last_query = query
        if self.failure is not None:
            raise self.failure
        if self.result_override is not None:
            return self.result_override
        if query.group_by == "month":
            return AnalyticsMetricResult(
                metric_key=query.metric_key,
                format=AnalyticsMetricFormat.NUMBER,
                group_by="month",
                points=(
                    AnalyticsDataPoint(
                        dimension=date(2026, 1, 1).strftime("%Y-%m"),
                        value=Decimal("7"),
                    ),
                ),
            )
        return AnalyticsMetricResult(
            metric_key=query.metric_key,
            format=AnalyticsMetricFormat.NUMBER,
            points=(AnalyticsDataPoint(value=Decimal("12")),),
        )


class FinanceAnalyticsProvider:
    module_key = "finance_test"

    def __init__(self) -> None:
        self.calls = 0
        self.last_context: AnalyticsProviderContext | None = None
        self.last_query: ValidatedAnalyticsMetricQuery | None = None

    def metrics(self) -> tuple[AnalyticsMetricDefinition, ...]:
        return (
            AnalyticsMetricDefinition(
                key="finance_test.total_cost",
                name_key="modules.finance_test.analytics.total_cost",
                format=AnalyticsMetricFormat.CURRENCY,
                required_permission="finance_test.entry.read",
                dimensions=(
                    AnalyticsDimensionDefinition(key="month"),
                    AnalyticsDimensionDefinition(key="category"),
                ),
                filters=(
                    AnalyticsFilterDefinition(
                        key="category_id",
                        value_type=AnalyticsFilterValueType.UUID,
                    ),
                    AnalyticsFilterDefinition(
                        key="minimum_cost",
                        value_type=AnalyticsFilterValueType.NUMBER,
                    ),
                ),
            ),
        )

    def query(
        self,
        *,
        session: Session,
        context: AnalyticsProviderContext,
        query: ValidatedAnalyticsMetricQuery,
    ) -> AnalyticsMetricResult:
        del session
        self.calls += 1
        self.last_context = context
        self.last_query = query
        points = (
            (AnalyticsDataPoint(value=Decimal("125.50")),)
            if query.group_by is None
            else (
                AnalyticsDataPoint(
                    dimension="Infrastructure",
                    value=Decimal("125.50"),
                ),
            )
        )
        return AnalyticsMetricResult(
            metric_key=query.metric_key,
            format=AnalyticsMetricFormat.CURRENCY,
            group_by=query.group_by,
            unit="BRL",
            points=points,
        )
