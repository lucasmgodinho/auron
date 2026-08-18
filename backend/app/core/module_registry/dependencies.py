from app.core.module_registry.registry import (
    ModuleRegistry,
    production_module_registry,
)


def get_module_registry() -> ModuleRegistry:
    return production_module_registry
