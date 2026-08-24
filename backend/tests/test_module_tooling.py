from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.core.module_registry.registry import production_module_registry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_SKILL = REPOSITORY_ROOT / ".agents" / "skills" / "auron-module"
HANDOFF_SKILL = REPOSITORY_ROOT / ".agents" / "skills" / "auron-handoff"


def load_script(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load test script: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def create_module_script() -> ModuleType:
    return load_script(
        "auron_create_module_test",
        MODULE_SKILL / "scripts" / "create_module.py",
    )


@pytest.fixture
def validate_module_script() -> ModuleType:
    return load_script(
        "auron_validate_module_test",
        MODULE_SKILL / "scripts" / "validate_module.py",
    )


@pytest.fixture
def collect_context_script() -> ModuleType:
    return load_script(
        "auron_collect_context_test",
        HANDOFF_SKILL / "scripts" / "collect_context.py",
    )


def isolated_project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    modules = root / "backend" / "app" / "modules"
    modules.mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test project\n", encoding="utf-8")
    source_registry = REPOSITORY_ROOT / "backend" / "app" / "modules" / "registry.py"
    (modules / "registry.py").write_text(
        source_registry.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return root


def test_scaffold_creates_and_validates_minimal_registered_module(
    tmp_path: Path,
    create_module_script: ModuleType,
    validate_module_script: ModuleType,
) -> None:
    root = isolated_project(tmp_path)

    paths = create_module_script.create_module(
        root=root,
        key="sample_test",
        name="Sample Test",
    )
    definition = validate_module_script.validate_module(
        root=root,
        key="sample_test",
    )

    module_dir = root / "backend" / "app" / "modules" / "sample_test"
    assert {path.name for path in paths} == {
        "__init__.py",
        "definition.py",
        "registry.py",
    }
    assert definition.key == "sample_test"
    assert definition.permissions == ()
    assert definition.analytics_provider is None
    assert (module_dir / "definition.py").read_text(encoding="utf-8").startswith(
        "'Sample Test'"
    )
    assert not (root / "frontend").exists()


@pytest.mark.parametrize("key", ["", "Fleet", "fleet-module", "1fleet", "fleet.module"])
def test_scaffold_rejects_invalid_module_keys(
    tmp_path: Path,
    create_module_script: ModuleType,
    key: str,
) -> None:
    root = isolated_project(tmp_path)
    with pytest.raises(create_module_script.ScaffoldError):
        create_module_script.create_module(root=root, key=key, name="Invalid")
    assert list((root / "backend" / "app" / "modules").iterdir()) == [
        root / "backend" / "app" / "modules" / "registry.py"
    ]


def test_scaffold_refuses_existing_target_and_dry_run_does_not_write(
    tmp_path: Path,
    create_module_script: ModuleType,
) -> None:
    root = isolated_project(tmp_path)
    dry_run_paths = create_module_script.create_module(
        root=root,
        key="dry_test",
        name="Dry Test",
        dry_run=True,
    )
    assert len(dry_run_paths) == 3
    assert not (root / "backend" / "app" / "modules" / "dry_test").exists()

    create_module_script.create_module(
        root=root,
        key="existing_test",
        name="Existing Test",
    )
    with pytest.raises(create_module_script.ScaffoldError):
        create_module_script.create_module(
            root=root,
            key="existing_test",
            name="Existing Test",
        )


def test_scaffold_registry_is_deterministic_for_reverse_creation_order(
    tmp_path: Path,
    create_module_script: ModuleType,
) -> None:
    reverse_root = isolated_project(tmp_path / "reverse")
    sorted_root = isolated_project(tmp_path / "sorted")

    for root, keys in (
        (reverse_root, ("zeta_test", "alpha_test")),
        (sorted_root, ("alpha_test", "zeta_test")),
    ):
        for key in keys:
            create_module_script.create_module(
                root=root,
                key=key,
                name=key.replace("_", " ").title(),
            )

    reverse_registry = (
        reverse_root / "backend" / "app" / "modules" / "registry.py"
    ).read_text(encoding="utf-8")
    sorted_registry = (
        sorted_root / "backend" / "app" / "modules" / "registry.py"
    ).read_text(encoding="utf-8")

    assert reverse_registry == sorted_registry
    assert reverse_registry.index("app.modules.alpha_test") < reverse_registry.index(
        "app.modules.zeta_test"
    )
    definitions = reverse_registry.split("PRODUCTION_MODULE_DEFINITIONS", 1)[1]
    assert definitions.index("ALPHA_TEST_MODULE_DEFINITION") < definitions.index(
        "ZETA_TEST_MODULE_DEFINITION"
    )


def test_optional_analytics_scaffold_uses_existing_contract_and_validates(
    tmp_path: Path,
    create_module_script: ModuleType,
    validate_module_script: ModuleType,
) -> None:
    root = isolated_project(tmp_path)
    create_module_script.create_module(
        root=root,
        key="metrics_test",
        name="Metrics Test",
        analytics=True,
    )

    definition = validate_module_script.validate_module(
        root=root,
        key="metrics_test",
    )

    assert definition.analytics_provider is not None
    assert definition.analytics_provider.module_key == "metrics_test"
    assert definition.analytics_provider.metrics() == ()
    analytics_source = (
        root / "backend" / "app" / "modules" / "metrics_test" / "analytics.py"
    ).read_text(encoding="utf-8")
    assert "app.core.analytics.provider" in analytics_source


def test_validator_rejects_permission_namespace_and_analytics_mismatch(
    tmp_path: Path,
    create_module_script: ModuleType,
    validate_module_script: ModuleType,
) -> None:
    root = isolated_project(tmp_path)
    create_module_script.create_module(
        root=root,
        key="invalid_permission_test",
        name="Invalid Permission",
    )
    definition_path = (
        root
        / "backend"
        / "app"
        / "modules"
        / "invalid_permission_test"
        / "definition.py"
    )
    definition_source = definition_path.read_text(encoding="utf-8").replace(
        "MODULE_PERMISSIONS: tuple[PermissionDefinition, ...] = ()",
        "MODULE_PERMISSIONS: tuple[PermissionDefinition, ...] = (\n"
        "    PermissionDefinition(\n"
        "        key=\"other_test.record.read\",\n"
        "        resource=\"record\",\n"
        "        action=\"read\",\n"
        "    ),\n"
        ")",
    )
    definition_path.write_text(definition_source, encoding="utf-8")
    with pytest.raises(validate_module_script.ModuleValidationError):
        validate_module_script.validate_module(root=root, key="invalid_permission_test")

    analytics_root = isolated_project(tmp_path / "analytics")
    create_module_script.create_module(
        root=analytics_root,
        key="invalid_analytics_test",
        name="Invalid Analytics",
        analytics=True,
    )
    analytics_path = (
        analytics_root
        / "backend"
        / "app"
        / "modules"
        / "invalid_analytics_test"
        / "analytics.py"
    )
    analytics_path.write_text(
        analytics_path.read_text(encoding="utf-8").replace(
            'module_key = "invalid_analytics_test"',
            'module_key = "another_test"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(validate_module_script.ModuleValidationError):
        validate_module_script.validate_module(
            root=analytics_root,
            key="invalid_analytics_test",
        )


def test_validator_cli_returns_nonzero_on_failure(tmp_path: Path) -> None:
    root = isolated_project(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_SKILL / "scripts" / "validate_module.py"),
            "missing_test",
            "--root",
            str(root),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "error:" in result.stderr


def test_tooling_never_mutates_production_registry(
    tmp_path: Path,
    create_module_script: ModuleType,
    validate_module_script: ModuleType,
) -> None:
    before = production_module_registry.list()
    root = isolated_project(tmp_path)
    create_module_script.create_module(
        root=root,
        key="isolated_test",
        name="Isolated Test",
    )
    validate_module_script.validate_module(root=root, key="isolated_test")
    assert production_module_registry.list() == before == ()


def test_handoff_git_metadata_parsing_is_deterministic(
    tmp_path: Path,
    collect_context_script: ModuleType,
) -> None:
    responses = {
        ("git", "branch", "--show-current"): "feature/module-standard",
        ("git", "rev-parse", "HEAD"): "abc123",
        ("git", "status", "--short"): " M AGENTS.md\n?? new-file.py",
    }

    def runner(command: tuple[str, ...], cwd: Path) -> str | None:
        assert cwd == tmp_path
        return responses[command]

    assert collect_context_script.collect_git_metadata(tmp_path, runner) == {
        "branch": "feature/module-standard",
        "head": "abc123",
        "working_tree_clean": False,
        "working_tree_changes": [" M AGENTS.md", "?? new-file.py"],
    }


def test_handoff_runner_preserves_git_porcelain_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    collect_context_script: ModuleType,
) -> None:
    def run(*args: object, **kwargs: object) -> SimpleNamespace:
        del args, kwargs
        return SimpleNamespace(stdout=" M tracked.py\n?? untracked.py\n")

    monkeypatch.setattr(collect_context_script.subprocess, "run", run)

    assert collect_context_script._run(("git", "status", "--short"), tmp_path) == (
        " M tracked.py\n?? untracked.py"
    )


def test_handoff_context_excludes_environment_secrets_and_registry_state(
    monkeypatch: pytest.MonkeyPatch,
    collect_context_script: ModuleType,
) -> None:
    secret = "must-never-appear-in-handoff-context"
    monkeypatch.setenv("HANDOFF_TEST_SECRET", secret)
    before = production_module_registry.list()

    def runner(command: tuple[str, ...], cwd: Path) -> str | None:
        del cwd
        if command[:2] == ("git", "branch"):
            return "main"
        if command[:2] == ("git", "rev-parse"):
            return "abc123"
        if command[:2] == ("git", "status"):
            return ""
        if command[-1] == "heads":
            return "0006_create_module_platform (head)"
        if command[-1] == "current":
            return "0006_create_module_platform (head)"
        return None

    context = collect_context_script.collect_context(REPOSITORY_ROOT, runner)
    serialized = json.dumps(context, sort_keys=True)

    assert secret not in serialized
    assert "HANDOFF_TEST_SECRET" not in serialized
    assert context["registry"] == {
        "production_modules": [],
        "analytics_providers": [],
    }
    assert production_module_registry.list() == before == ()
    assert not (REPOSITORY_ROOT / ".ai" / "AURON_HANDOFF.md").exists()
    assert os.environ["HANDOFF_TEST_SECRET"] == secret
