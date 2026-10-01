"""Back up live service directories under services/<name>/."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def _backup_ignore(names: set[str]):
    """shutil.copytree ignore callback for relative paths under services/<name>/."""

    def _ignore(_dir: str, entries: list[str]) -> set[str]:
        return {entry for entry in entries if entry in names}

    return _ignore


def _docker_pg_dump(container: str, user: str, database: str, dest: Path) -> None:
    result = subprocess.run(
        ["docker", "exec", container, "pg_dump", "-U", user, "-Fc", database],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise BackupError(
            f"pg_dump failed for {container}/{database}: {stderr or result.returncode}"
        )
    dest.write_bytes(result.stdout)


def _write_backup_manifest(
    dest: Path,
    *,
    service: str,
    strategy: str,
    excludes: list[str],
    extras: list[str],
) -> None:
    manifest = {
        "service": service,
        "strategy": strategy,
        "timestamp": dest.name,
        "excludes": excludes,
        "extras": extras,
    }
    (dest / "backup.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def backup_paperless(
    name: str,
    data_dir: Path,
    *,
    label: str | None = None,
    exclude: list[str] | None = None,
) -> Path:
    """Copy Paperless files (excluding live db/redis dirs) plus a PostgreSQL dump."""
    excludes = exclude or ["db", "redis"]
    dest = backup_service(name, data_dir, label=label, exclude=excludes)
    dump_path = dest / "postgres.dump"
    _docker_pg_dump("paperless-db", "paperless", "paperless", dump_path)
    _write_backup_manifest(
        dest,
        service=name,
        strategy="paperless",
        excludes=excludes,
        extras=["postgres.dump"],
    )
    return dest


BACKUP_HANDLERS: dict[str, Callable[..., Path]] = {
    "paperless": backup_paperless,
}


def backup_service(
    name: str,
    data_dir: Path,
    *,
    label: str | None = None,
    exclude: list[str] | None = None,
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
    ignore = _backup_ignore(set(exclude or ()))
    shutil.copytree(src, dest, symlinks=True, ignore=ignore)
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
    registry = load_registry()
    targets = resolve_backup_targets(services, backup_all, registry)
    if not targets:
        raise BackupError("Specify service names or --all")

    data_dir, _repo = resolve_backup_data_dir(root)
    services_map: dict[str, Any] = registry.get("services", {})

    results: list[Path] = []
    for name in targets:
        svc = services_map.get(name, {})
        exclude = svc.get("backup_exclude")
        strategy = svc.get("backup_strategy")
        if strategy:
            handler = BACKUP_HANDLERS.get(strategy)
            if handler is None:
                raise BackupError(f"Unknown backup_strategy {strategy!r} for {name}")
            dest = handler(name, data_dir, label=label, exclude=exclude)
        else:
            dest = backup_service(name, data_dir, label=label, exclude=exclude)
        results.append(dest)
        try:
            rel = dest.relative_to(data_dir)
        except ValueError:
            rel = dest
        extra = " (+ postgres.dump)" if strategy == "paperless" else ""
        print(f"Backed up {name} → {rel}{extra}")
    return results
