from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

Runner = Callable[[tuple[str, ...], Path], str | None]


def _repository_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "AGENTS.md").is_file() and (parent / "backend").is_dir():
            return parent
    raise RuntimeError("Could not locate the Auron repository root")


def _run(command: tuple[str, ...], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.rstrip()


def collect_git_metadata(root: Path, runner: Runner = _run) -> dict[str, object]:
    branch = runner(("git", "branch", "--show-current"), root)
    head = runner(("git", "rev-parse", "HEAD"), root)
    status = runner(("git", "status", "--short"), root)
    changes = [] if not status else status.splitlines()
    return {
        "branch": branch or "unavailable",
        "head": head or "unavailable",
        "working_tree_clean": not changes,
        "working_tree_changes": changes,
    }


def _alembic_command(root: Path) -> tuple[str, ...]:
    candidates = (
        root / "backend" / ".venv" / "Scripts" / "alembic.exe",
        root / "backend" / ".venv" / "bin" / "alembic",
    )
    for candidate in candidates:
        if candidate.is_file():
            return (str(candidate),)
    return (sys.executable, "-m", "alembic")


def collect_alembic_metadata(root: Path, runner: Runner = _run) -> dict[str, str]:
    command = _alembic_command(root)
    backend = root / "backend"
    heads = runner((*command, "heads"), backend)
    current = runner((*command, "current"), backend)
    return {
        "head": heads or "unavailable",
        "current": current or "unavailable",
    }


def collect_registry_metadata(root: Path) -> dict[str, object]:
    backend = str(root / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from app.core.module_registry.registry import (
        production_module_registry,
    )
    from app.modules import registry as _module_composition  # noqa: F401

    modules = production_module_registry.list()
    providers = [
        {
            "module_key": module.key,
            "metric_keys": [
                metric.key
                for metric in production_module_registry.list_analytics_metrics(module.key)
            ],
        }
        for module in modules
        if module.analytics_provider is not None
    ]
    return {
        "production_modules": [module.key for module in modules],
        "analytics_providers": providers,
    }


def collect_context(root: Path, runner: Runner = _run) -> dict[str, object]:
    root = root.resolve()
    important_paths = (
        "AGENTS.md",
        "README.md",
        "docs/ARCHITECTURE.md",
        "docs/MODULE_CONTRACT.md",
        "backend/app/main.py",
        "backend/app/core/module_registry/registry.py",
        "backend/app/core/access_control/service.py",
        "backend/app/core/analytics/service.py",
        "backend/app/modules/registry.py",
        "frontend/src/App.tsx",
    )
    return {
        "snapshot_date": datetime.now(UTC).date().isoformat(),
        "git": collect_git_metadata(root, runner),
        "alembic": collect_alembic_metadata(root, runner),
        "registry": collect_registry_metadata(root),
        "important_paths": {
            path: (root / path).is_file() for path in important_paths
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect deterministic Auron handoff facts")
    parser.add_argument("--root", type=Path, default=_repository_root(), help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    print(json.dumps(collect_context(args.root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
