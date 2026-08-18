from dataclasses import dataclass


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
