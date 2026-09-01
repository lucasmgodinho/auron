'Competitive Intelligence'

from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)

MODULE_KEY = "competitive_intelligence"
RUN_ANALYSIS_PERMISSION = "competitive_intelligence.analysis.run"

MODULE_PERMISSIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition(
        key=RUN_ANALYSIS_PERMISSION,
        resource="analysis",
        action="run",
    ),
)

MODULE_DEFINITION = ModuleDefinition(
    key=MODULE_KEY,
    name_key="modules.competitive_intelligence.name",
    permissions=MODULE_PERMISSIONS,
)
