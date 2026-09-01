import pytest

from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)
from app.core.module_registry.registry import (
    DuplicateModuleError,
    DuplicatePermissionError,
    InvalidModuleDefinitionError,
    ModuleRegistry,
    production_module_registry,
)


def permission(key: str, resource: str = "record", action: str = "read") -> PermissionDefinition:
    return PermissionDefinition(key=key, resource=resource, action=action)


def module(
    key: str = "operations_test",
    permissions: tuple[PermissionDefinition, ...] | None = None,
) -> ModuleDefinition:
    return ModuleDefinition(
        key=key,
        name_key=f"modules.{key}.name",
        permissions=permissions
        if permissions is not None
        else (permission(f"{key}.record.read"),),
    )


def test_valid_module_registration_and_lookup() -> None:
    definition = module()
    registry = ModuleRegistry([definition])

    assert registry.has(definition.key)
    assert registry.get(definition.key) is definition
    assert registry.list() == (definition,)
    assert registry.get_permission("operations_test.record.read") is definition.permissions[0]
    assert registry.get("missing") is None
    assert registry.get_permission("missing.record.read") is None


@pytest.mark.parametrize("key", ["", "Fleet", "fleet-module", "1fleet", "fleet.module"])
def test_invalid_module_key_is_rejected(key: str) -> None:
    with pytest.raises(InvalidModuleDefinitionError):
        ModuleRegistry([module(key=key)])


def test_duplicate_module_key_is_rejected() -> None:
    registry = ModuleRegistry([module()])

    with pytest.raises(DuplicateModuleError):
        registry.register(module())


def test_duplicate_permission_key_is_rejected() -> None:
    duplicate = permission("operations_test.record.read")

    with pytest.raises(DuplicatePermissionError):
        ModuleRegistry([module(permissions=(duplicate, duplicate))])


@pytest.mark.parametrize(
    "definition",
    [
        module(permissions=(permission("record.read"),)),
        module(permissions=(permission("another.record.read"),)),
        module(permissions=(permission("operations_test.record"),)),
        module(permissions=(permission("operations_test.Record.read"),)),
        module(
            permissions=(
                permission(
                    "operations_test.record.create",
                    resource="record",
                    action="read",
                ),
            )
        ),
    ],
)
def test_invalid_permission_definition_is_rejected(
    definition: ModuleDefinition,
) -> None:
    with pytest.raises(InvalidModuleDefinitionError):
        ModuleRegistry([definition])


def test_production_registry_contains_no_fake_or_unimplemented_modules() -> None:
    forbidden = {
        "operations_test",
        "test_module",
        "fleet",
        "analytics",
        "cost_management",
    }

    assert {
        definition.key for definition in production_module_registry.list()
    } == {"competitive_intelligence"}
    assert forbidden.isdisjoint(
        definition.key for definition in production_module_registry.list()
    )
