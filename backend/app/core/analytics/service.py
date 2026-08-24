from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.access_control import service as access_service
from app.core.analytics.definitions import AnalyticsMetricDefinition
from app.core.analytics.provider import AnalyticsProvider, AnalyticsProviderContext
from app.core.analytics.schemas import AnalyticsMetricQuery, AnalyticsMetricResult
from app.core.analytics.validation import validate_metric_query, validate_metric_result
from app.core.module_registry.definitions import ModuleDefinition
from app.core.module_registry.registry import ModuleRegistry
from app.core.organization_context.context import OrganizationContext


class AnalyticsMetricNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedAnalyticsMetric:
    module: ModuleDefinition
    provider: AnalyticsProvider
    metric: AnalyticsMetricDefinition


def get_metric(registry: ModuleRegistry, metric_key: str) -> ResolvedAnalyticsMetric:
    module_key, separator, _ = metric_key.partition(".")
    if not separator:
        raise AnalyticsMetricNotFoundError
    module = registry.get(module_key)
    if module is None or module.analytics_provider is None:
        raise AnalyticsMetricNotFoundError
    metric = registry.get_analytics_metric(metric_key)
    if metric is None:
        raise AnalyticsMetricNotFoundError
    return ResolvedAnalyticsMetric(
        module=module,
        provider=module.analytics_provider,
        metric=metric,
    )


def list_provider_metrics(
    registry: ModuleRegistry, module_key: str
) -> tuple[AnalyticsMetricDefinition, ...]:
    module = registry.get(module_key)
    if module is None or module.analytics_provider is None:
        return ()
    return registry.list_analytics_metrics(module_key)


def list_available_metrics(
    session: Session,
    *,
    context: OrganizationContext,
    registry: ModuleRegistry,
) -> tuple[AnalyticsMetricDefinition, ...]:
    access = access_service.get_effective_access(
        session,
        context=context,
        registry=registry,
    )
    enabled_modules = set(access.enabled_module_keys)
    permissions = set(access.permission_keys)
    available: list[AnalyticsMetricDefinition] = []
    for module in registry.list():
        if module.key not in enabled_modules or module.analytics_provider is None:
            continue
        available.extend(
            metric
            for metric in registry.list_analytics_metrics(module.key)
            if metric.required_permission in permissions
        )
    return tuple(sorted(available, key=lambda metric: metric.key))


def query_metric(
    session: Session,
    *,
    context: OrganizationContext,
    registry: ModuleRegistry,
    query: AnalyticsMetricQuery,
) -> AnalyticsMetricResult:
    resolved = get_metric(registry, query.metric_key)
    access_service.authorize_module_permission(
        session,
        context=context,
        registry=registry,
        module_key=resolved.module.key,
        permission_key=resolved.metric.required_permission,
    )
    validated_query = validate_metric_query(resolved.metric, query)
    result = resolved.provider.query(
        session=session,
        context=AnalyticsProviderContext(
            organization_id=context.organization.id,
        ),
        query=validated_query,
    )
    return validate_metric_result(
        metric=resolved.metric,
        query=validated_query,
        result=result,
    )
