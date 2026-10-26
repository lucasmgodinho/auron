from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType


class ModuleValidationError(Exception):
    pass


def _repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "AGENTS.md").is_file() and (parent / "backend").is_dir():
            return parent
    raise ModuleValidationError("Could not locate the Auron repository root")


def _add_backend_to_path(root: Path) -> None:
    backend = str(root / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)


def _load_definition(root: Path, key: str) -> object:
    module_dir = root / "backend" / "app" / "modules" / key
    definition_path = module_dir / "definition.py"
    if not definition_path.is_file():
        raise ModuleValidationError(f"Module definition not found: {definition_path}")

    package_name = f"_auron_module_validation_{key}"
    package = ModuleType(package_name)
    package.__path__ = [str(module_dir)]  # type: ignore[attr-defined]
    sys.modules[package_name] = package
    try:
        spec = importlib.util.spec_from_file_location(
            f"{package_name}.definition",
            definition_path,
        )
        if spec is None or spec.loader is None:
            raise ModuleValidationError("Could not load module definition")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        definition = getattr(module, "MODULE_DEFINITION", None)
        if definition is None:
            raise ModuleValidationError("definition.py must expose MODULE_DEFINITION")
        return definition
    except ModuleValidationError:
        raise
    except Exception as error:
        raise ModuleValidationError(f"Could not import module definition: {error}") from error
    finally:
        for name in tuple(sys.modules):
            if name == package_name or name.startswith(f"{package_name}."):
                sys.modules.pop(name, None)


def _validate_registration(root: Path, key: str) -> None:
    registry_path = root / "backend" / "app" / "modules" / "registry.py"
    if not registry_path.is_file():
        raise ModuleValidationError("Production module registry is missing")
    source = registry_path.read_text(encoding="utf-8")
    constant = f"{key.upper()}_MODULE_DEFINITION"
    import_line = (
        f"from app.modules.{key}.definition import (\n"
        f"    MODULE_DEFINITION as {constant},\n"
        ")"
    )
    registered = re.search(
        rf"^\s+{constant},\s*$", source, re.MULTILINE
    )
    if import_line not in source or registered is None:
        raise ModuleValidationError(
            f"Module is not registered in backend/app/modules/registry.py: {key}"
        )


def _validate_frontend_localization(root: Path, key: str) -> None:
    frontend_module = root / "frontend" / "src" / "modules" / key
    if not frontend_module.exists():
        return
    for locale in ("en.ts", "pt-BR.ts"):
        locale_path = root / "frontend" / "src" / "i18n" / "locales" / locale
        if not locale_path.is_file() or re.search(
            rf"\b{re.escape(key)}\s*:\s*{{",
            locale_path.read_text(encoding="utf-8"),
        ) is None:
            raise ModuleValidationError(
                f"Frontend module requires localization in {locale_path}: {key}"
            )


def validate_module(*, root: Path, key: str) -> object:
    root = root.resolve()
    _add_backend_to_path(_repository_root())
    from app.core.module_registry.registry import (
        InvalidModuleDefinitionError,
        ModuleRegistry,
        validate_identifier,
    )

    try:
        validate_identifier(key, "module key")
    except InvalidModuleDefinitionError as error:
        raise ModuleValidationError(str(error)) from error
    definition = _load_definition(root, key)
    if getattr(definition, "key", None) != key:
        raise ModuleValidationError("ModuleDefinition key does not match the module path")
    try:
        ModuleRegistry([definition])
    except Exception as error:
        raise ModuleValidationError(f"ModuleDefinition is invalid: {error}") from error
    _validate_registration(root, key)
    _validate_frontend_localization(root, key)
    return definition


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate an Auron business module")
    parser.add_argument("module_key", help="Stable module key")
    parser.add_argument(
        "--root",
        type=Path,
        default=_repository_root(),
        help=argparse.SUPPRESS,
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        definition = validate_module(root=args.root, key=args.module_key)
    except ModuleValidationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"Valid Auron module: {definition.key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
