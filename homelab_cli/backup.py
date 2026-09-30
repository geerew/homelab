"""Back up live service directories under services/<name>/."""

from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from homelab_cli.config import load_config, resolve_data_dir
from homelab_cli.paths import config_file, repo_root
from homelab_cli.registry import backupable_services, load_registry


class BackupError(Exception):
    """Backup could not be completed."""


def backup_timestamp(label: str | None = None) -> str:
    """UTC folder name; optional label prefix (e.g. manual-20260929T191045Z)."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{label}-{ts}" if label else ts


def resolve_backup_data_dir(root: Path | None = None) -> tuple[Path, Path]:
    """Return (data_dir, repo_root). Uses homelab.yaml when present, else repo root."""
    root = root or repo_root()
    cfg_path = config_file(root)
    if cfg_path.is_file():
        return resolve_data_dir(load_config(cfg_path)), root
    print(
        f"Note: {cfg_path} not found — using {root} for services/ and backups/",
        file=sys.stderr,
    )
    return root, root


def backup_service(
    name: str,
    data_dir: Path,
    *,
    label: str | None = None,
) -> Path:
    """Copy services/<name>/ to backups/<name>/<timestamp>/; return destination path."""
    src = data_dir / "services" / name
    if not src.is_dir():
        raise BackupError(f"Service directory not found: {src}")

    stamp = backup_timestamp(label)
    dest = data_dir / "backups" / name / stamp
    if dest.exists():
        raise BackupError(f"Backup already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, symlinks=True)
    return dest


def resolve_backup_targets(
    services: list[str] | None = None,
    backup_all: bool = False,
    registry: dict | None = None,
) -> list[str]:
    reg = registry or load_registry()
    if backup_all:
        return backupable_services(reg)
    if services:
        return list(dict.fromkeys(services))
    return []


def run_backup(
    services: list[str] | None = None,
    backup_all: bool = False,
    label: str | None = None,
    root: Path | None = None,
) -> list[Path]:
    """Back up one or more services; print-friendly paths returned."""
    root = root or repo_root()
    targets = resolve_backup_targets(services, backup_all)
    if not targets:
        raise BackupError("Specify service names or --all")

    data_dir, _repo = resolve_backup_data_dir(root)

    results: list[Path] = []
    for name in targets:
        dest = backup_service(name, data_dir, label=label)
        results.append(dest)
        try:
            rel = dest.relative_to(data_dir)
        except ValueError:
            rel = dest
        print(f"Backed up {name} → {rel}")
    return results
