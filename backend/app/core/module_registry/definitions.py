from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.analytics.provider import AnalyticsProvider


@dataclass(frozen=True, slots=True)
class PermissionDefinition:
    key: str
    resource: str
    action: str


@dataclass(frozen=True, slots=True)
class ModuleDefinition:
    key: str
    name_key: str
    permissions: tuple[PermissionDefinition, ...]
    analytics_provider: AnalyticsProvider | None = None
