"""Restore service backups created by homelab backup."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from homelab_cli.config import load_config, resolve_data_dir
from homelab_cli.paths import config_file, repo_root
from homelab_cli.registry import load_registry


class RestoreError(Exception):
    """Restore could not be completed."""


def _run_docker(args: list[str], *, input_bytes: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", *args],
        input=input_bytes,
        capture_output=True,
        check=False,
    )


def resolve_backup_dir(service: str, backup_id: str, data_dir: Path) -> Path:
    candidate = Path(backup_id)
    if candidate.is_dir():
        return candidate.resolve()
    backup_dir = data_dir / "backups" / service / backup_id
    if backup_dir.is_dir():
        return backup_dir
    raise RestoreError(f"Backup not found: {backup_id} (looked in {backup_dir})")


def list_backups(service: str, data_dir: Path) -> list[Path]:
    root = data_dir / "backups" / service
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)


def restore_paperless(backup_dir: Path, data_dir: Path) -> None:
    dump_path = backup_dir / "postgres.dump"
    if not dump_path.is_file():
        raise RestoreError(f"Missing postgres.dump in {backup_dir}")

    dest = data_dir / "services" / "paperless"
    if not dest.is_dir():
        raise RestoreError(f"Service directory not found: {dest}")

    print("Stopping paperless…", file=sys.stderr)
    _run_docker(["stop", "paperless"])

    print(f"Restoring files from {backup_dir} → {dest}", file=sys.stderr)
    for item in backup_dir.iterdir():
        if item.name in {"postgres.dump", "backup.json"}:
            continue
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target, symlinks=True)
        else:
            shutil.copy2(item, target)

    print("Restoring PostgreSQL database…", file=sys.stderr)
    restore = _run_docker(
        [
            "exec",
            "-i",
            "paperless-db",
            "pg_restore",
            "-U",
            "paperless",
            "-d",
            "paperless",
            "--clean",
            "--if-exists",
            "--no-owner",
        ],
        input_bytes=dump_path.read_bytes(),
    )
    if restore.returncode != 0:
        stderr = restore.stderr.decode("utf-8", errors="replace").strip()
        raise RestoreError(f"pg_restore failed: {stderr or restore.returncode}")

    print("Starting paperless…", file=sys.stderr)
    start = _run_docker(["start", "paperless"])
    if start.returncode != 0:
        stderr = start.stderr.decode("utf-8", errors="replace").strip()
        raise RestoreError(f"Failed to start paperless: {stderr or start.returncode}")


RESTORE_HANDLERS: dict[str, Any] = {
    "paperless": restore_paperless,
}


def run_restore(service: str, backup_id: str, *, root: Path | None = None) -> None:
    root = root or repo_root()
    cfg_path = config_file(root)
    if not cfg_path.is_file():
        raise RestoreError(f"Missing config: {cfg_path}")
    data_dir = resolve_data_dir(load_config(cfg_path))

    registry = load_registry()
    strategy = registry.get("services", {}).get(service, {}).get("backup_strategy")
    if not strategy:
        raise RestoreError(f"Service {service!r} has no backup_strategy — restore not supported")
    handler = RESTORE_HANDLERS.get(strategy)
    if handler is None:
        raise RestoreError(f"No restore handler for backup_strategy {strategy!r}")

    backup_dir = resolve_backup_dir(service, backup_id, data_dir)
    manifest_path = backup_dir / "backup.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("strategy") != strategy:
            raise RestoreError(
                f"Backup strategy mismatch: expected {strategy!r}, got {manifest.get('strategy')!r}"
            )

    handler(backup_dir, data_dir)
