from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

IMPORT_MARKER = "# AURON_MODULE_IMPORTS"
DEFINITION_MARKER = "    # AURON_MODULE_DEFINITIONS"


class ScaffoldError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PlannedFile:
    path: Path
    content: str


def _skill_repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "AGENTS.md").is_file() and (parent / "backend").is_dir():
            return parent
    raise ScaffoldError("Could not locate the Auron repository root")


def _add_backend_to_path(root: Path) -> None:
    backend = str(root / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _validate_key(key: str) -> None:
    _add_backend_to_path(_skill_repository_root())
    from app.core.module_registry.registry import (
        InvalidModuleDefinitionError,
        validate_identifier,
    )

    try:
        validate_identifier(key, "module key")
    except InvalidModuleDefinitionError as error:
        raise ScaffoldError(str(error)) from error


def _class_prefix(key: str) -> str:
    return "".join(part.capitalize() for part in key.split("_"))


def _definition_content(key: str, name: str, analytics: bool) -> str:
    analytics_import = ""
    analytics_argument = ""
    if analytics:
        analytics_import = "from .analytics import ANALYTICS_PROVIDER\n\n"
        analytics_argument = ",\n    analytics_provider=ANALYTICS_PROVIDER"
    return (
        f"{name!r}\n\n"
        "from app.core.module_registry.definitions import (\n"
        "    ModuleDefinition,\n"
        "    PermissionDefinition,\n"
        ")\n\n"
        f"{analytics_import}"
        "MODULE_PERMISSIONS: tuple[PermissionDefinition, ...] = ()\n\n"
        "MODULE_DEFINITION = ModuleDefinition(\n"
        f'    key="{key}",\n'
        f'    name_key="modules.{key}.name",\n'
        f"    permissions=MODULE_PERMISSIONS{analytics_argument},\n"
        ")\n"
    )


def _analytics_content(key: str) -> str:
    provider_name = f"{_class_prefix(key)}AnalyticsProvider"
    return (
        "from sqlalchemy.orm import Session\n\n"
        "from app.core.analytics.definitions import AnalyticsMetricDefinition\n"
        "from app.core.analytics.provider import (\n"
        "    AnalyticsProviderContext,\n"
        "    ValidatedAnalyticsMetricQuery,\n"
        ")\n"
        "from app.core.analytics.schemas import AnalyticsMetricResult\n\n\n"
        f"class {provider_name}:\n"
        f'    module_key = "{key}"\n\n'
        "    def metrics(self) -> tuple[AnalyticsMetricDefinition, ...]:\n"
        "        return ()\n\n"
        "    def query(\n"
        "        self,\n"
        "        *,\n"
        "        session: Session,\n"
        "        context: AnalyticsProviderContext,\n"
        "        query: ValidatedAnalyticsMetricQuery,\n"
        "    ) -> AnalyticsMetricResult:\n"
        "        del session, context\n"
        "        raise ValueError(f\"Unknown metric: {query.metric_key}\")\n\n\n"
        f"ANALYTICS_PROVIDER = {provider_name}()\n"
    )


def _planned_files(
    root: Path, key: str, name: str, analytics: bool
) -> tuple[PlannedFile, ...]:
    module_dir = root / "backend" / "app" / "modules" / key
    files = [
        PlannedFile(
            module_dir / "__init__.py",
            "from .definition import MODULE_DEFINITION\n\n__all__ = [\"MODULE_DEFINITION\"]\n",
        ),
        PlannedFile(
            module_dir / "definition.py",
            _definition_content(key, name, analytics),
        ),
    ]
    if analytics:
        files.append(PlannedFile(module_dir / "analytics.py", _analytics_content(key)))
    return tuple(files)


def _updated_registry(source: str, key: str) -> str:
    if IMPORT_MARKER not in source or DEFINITION_MARKER not in source:
        raise ScaffoldError("Module registry does not contain the scaffold markers")
    constant = f"{key.upper()}_MODULE_DEFINITION"
    import_line = (
        f"from app.modules.{key}.definition import (\n"
        f"    MODULE_DEFINITION as {constant},\n"
        ")\n"
    )
    definition_line = f"    {constant},\n"
    if import_line in source or definition_line in source:
        raise ScaffoldError(f"Module is already registered: {key}")
    source = source.replace(IMPORT_MARKER, f"{import_line}{IMPORT_MARKER}", 1)
    return source.replace(DEFINITION_MARKER, f"{definition_line}{DEFINITION_MARKER}", 1)


def create_module(
    *,
    root: Path,
    key: str,
    name: str,
    analytics: bool = False,
    dry_run: bool = False,
) -> tuple[Path, ...]:
    _validate_key(key)
    if not name.strip():
        raise ScaffoldError("Module name is required")
    root = root.resolve()
    files = _planned_files(root, key, name.strip(), analytics)
    module_dir = files[0].path.parent
    if module_dir.exists() or any(item.path.exists() for item in files):
        raise ScaffoldError(f"Module target already exists: {module_dir}")

    registry_path = root / "backend" / "app" / "modules" / "registry.py"
    if not registry_path.is_file():
        raise ScaffoldError(f"Module registry not found: {registry_path}")
    registry_content = _updated_registry(registry_path.read_text(encoding="utf-8"), key)
    paths = tuple(item.path for item in files) + (registry_path,)
    if dry_run:
        return paths

    module_dir.mkdir(parents=False)
    for item in files:
        item.path.write_text(item.content, encoding="utf-8", newline="\n")
    registry_path.write_text(registry_content, encoding="utf-8", newline="\n")
    return paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a minimal Auron business module")
    parser.add_argument("--key", required=True, help="Stable lowercase module key")
    parser.add_argument("--name", required=True, help="Human module name")
    parser.add_argument("--analytics", action="store_true", help="Add AnalyticsProvider structure")
    parser.add_argument("--dry-run", action="store_true", help="List changes without writing")
    parser.add_argument(
        "--root",
        type=Path,
        default=_skill_repository_root(),
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        paths = create_module(
            root=args.root,
            key=args.key,
            name=args.name,
            analytics=args.analytics,
            dry_run=args.dry_run,
        )
    except ScaffoldError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    action = "Would update" if args.dry_run else "Updated"
    for path in paths:
        print(f"{action}: {path.relative_to(args.root.resolve())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
