"""Docker Compose wrappers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from homelab_cli.compose import render_compose
from homelab_cli.paths import repo_root
from homelab_cli.registry import all_compose_services, expand_services


def _compose_cmd(*args: str, root: Path | None = None) -> list[str]:
    return ["docker", "compose", "-f", str((root or repo_root()) / "compose.yaml"), *args]


def run_compose(args: list[str], root: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = _compose_cmd(*args, root=root)
    return subprocess.run(cmd, cwd=root or repo_root(), check=check, text=True)


def up(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    args = ["up", "-d"]
    if services:
        args.extend(expand_services(services, operation="up"))
    run_compose(args, root=root)


def down(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    if services:
        run_compose(["stop", *expand_services(services, operation="down")], root=root)
    else:
        run_compose(["down"], root=root)


def start(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    targets = (
        expand_services(services, operation="start")
        if services
        else all_compose_services()
    )
    run_compose(["start", *targets], root=root)


def stop(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    targets = (
        expand_services(services, operation="stop")
        if services
        else all_compose_services()
    )
    run_compose(["stop", *targets], root=root)


def restart(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    targets = (
        expand_services(services, operation="restart")
        if services
        else all_compose_services()
    )
    run_compose(["restart", *targets], root=root)
