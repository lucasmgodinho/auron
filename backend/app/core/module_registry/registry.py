import re
from collections.abc import Iterable

from app.core.module_registry.definitions import (
    ModuleDefinition,
    PermissionDefinition,
)

IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class InvalidModuleDefinitionError(ValueError):
    pass


class DuplicateModuleError(ValueError):
    pass


class DuplicatePermissionError(ValueError):
    pass


class ModuleRegistry:
    def __init__(self, definitions: Iterable[ModuleDefinition] = ()) -> None:
        self._modules: dict[str, ModuleDefinition] = {}
        self._permissions: dict[str, PermissionDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: ModuleDefinition) -> None:
        self._validate_module(definition)
        if definition.key in self._modules:
            raise DuplicateModuleError(f"Module already registered: {definition.key}")

        permission_keys = {permission.key for permission in definition.permissions}
        duplicates = permission_keys.intersection(self._permissions)
        if duplicates:
            duplicate = sorted(duplicates)[0]
            raise DuplicatePermissionError(f"Permission already registered: {duplicate}")
        if len(permission_keys) != len(definition.permissions):
            raise DuplicatePermissionError(
                f"Module contains duplicate permissions: {definition.key}"
            )

        self._modules[definition.key] = definition
        self._permissions.update(
            (permission.key, permission) for permission in definition.permissions
        )

    def get(self, module_key: str) -> ModuleDefinition | None:
        return self._modules.get(module_key)

    def list(self) -> tuple[ModuleDefinition, ...]:
        return tuple(self._modules[key] for key in sorted(self._modules))

    def has(self, module_key: str) -> bool:
        return module_key in self._modules

    def get_permission(self, permission_key: str) -> PermissionDefinition | None:
        return self._permissions.get(permission_key)

    @staticmethod
    def _validate_module(definition: ModuleDefinition) -> None:
        validate_identifier(definition.key, "module key")
        if not definition.name_key.strip():
            raise InvalidModuleDefinitionError("Module name key is required")
        for permission in definition.permissions:
            validate_permission_definition(definition.key, permission)


def validate_identifier(value: str, label: str) -> None:
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise InvalidModuleDefinitionError(f"Invalid {label}: {value}")


def validate_permission_definition(
    module_key: str, permission: PermissionDefinition
) -> None:
    validate_identifier(permission.resource, "permission resource")
    validate_identifier(permission.action, "permission action")
    expected_key = f"{module_key}.{permission.resource}.{permission.action}"
    if permission.key != expected_key:
        raise InvalidModuleDefinitionError(
            f"Permission key must be {expected_key}: {permission.key}"
        )


production_module_registry = ModuleRegistry()
