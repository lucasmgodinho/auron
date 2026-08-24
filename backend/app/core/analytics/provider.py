from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.analytics.definitions import AnalyticsMetricDefinition
from app.core.analytics.schemas import AnalyticsMetricResult

AnalyticsFilterValue = str | int | Decimal | bool | date | datetime | UUID


@dataclass(frozen=True, slots=True)
class AnalyticsProviderContext:
    organization_id: UUID


@dataclass(frozen=True, slots=True)
class ValidatedAnalyticsMetricQuery:
    metric_key: str
    group_by: str | None
    filters: MappingProxyType[str, AnalyticsFilterValue]


class AnalyticsProvider(Protocol):
    @property
    def module_key(self) -> str: ...

    def metrics(self) -> tuple[AnalyticsMetricDefinition, ...]: ...

    def query(
        self,
        *,
        session: Session,
        context: AnalyticsProviderContext,
        query: ValidatedAnalyticsMetricQuery,
    ) -> AnalyticsMetricResult: ...
