from app.core.module_registry.definitions import ModuleDefinition
from app.core.module_registry.registry import production_module_registry

# AURON_MODULE_IMPORTS

PRODUCTION_MODULE_DEFINITIONS: tuple[ModuleDefinition, ...] = (
    # AURON_MODULE_DEFINITIONS
)

for module_definition in PRODUCTION_MODULE_DEFINITIONS:
    production_module_registry.register(module_definition)
