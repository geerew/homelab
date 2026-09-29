"""Repository path resolution."""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    env = os.environ.get("HOMELAB_DIR", "").strip()
    if env:
        return Path(env).resolve()
    # homelab_cli/ lives at repo root
    return Path(__file__).resolve().parent.parent


def config_file(root: Path | None = None) -> Path:
    return (root or repo_root()) / "homelab.yaml"


def example_config_file(root: Path | None = None) -> Path:
    return (root or repo_root()) / "homelab.example.yaml"


def compose_template(root: Path | None = None) -> Path:
    return (root or repo_root()) / "compose.tpl.yaml"


def compose_output(root: Path | None = None) -> Path:
    return (root or repo_root()) / "compose.yaml"


def services_registry(root: Path | None = None) -> Path:
    return (root or repo_root()) / "config" / "services.yaml"


def ansible_dir(root: Path | None = None) -> Path:
    return (root or repo_root()) / "ansible"
