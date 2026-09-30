"""Docker Compose wrappers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from homelab_cli.compose import render_compose
from homelab_cli.paths import repo_root
from homelab_cli.registry import all_compose_services, expand_services, load_registry


def _docker_inspect(name: str, fmt: str) -> str | None:
    result = subprocess.run(
        ["docker", "inspect", name, "--format", fmt],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _container_id(name: str) -> str | None:
    return _docker_inspect(name, "{{.Id}}")


def _gluetun_sidecars(registry: dict | None = None) -> list[str]:
    reg = registry or load_registry()
    stack = reg.get("stacks", {}).get("gluetun_vpn", [])
    return [service for service in stack if service != "gluetun"]


def _sidecar_network_target(service: str) -> str | None:
    mode = _docker_inspect(service, "{{.HostConfig.NetworkMode}}")
    if not mode or not mode.startswith("container:"):
        return mode
    return mode.split(":", 1)[1]


def find_stale_gluetun_sidecars(registry: dict | None = None) -> list[str]:
    """Return sidecar services not attached to the current Gluetun network namespace."""
    gluetun_id = _container_id("gluetun")
    if not gluetun_id:
        return []

    stale: list[str] = []
    for service in _gluetun_sidecars(registry):
        target = _sidecar_network_target(service)
        if target is None:
            continue
        if target in {"bridge", "default", "host", "none"}:
            stale.append(service)
            continue
        attached_id = _container_id(target) if target != gluetun_id else gluetun_id
        if attached_id != gluetun_id:
            stale.append(service)
    return stale


def sync_gluetun_sidecars(root: Path | None = None) -> list[str]:
    """Recreate sidecars still attached to an old Gluetun network namespace."""
    stale = find_stale_gluetun_sidecars()
    if not stale:
        return []

    run_compose(["up", "-d", "--force-recreate", *stale], root=root, check=True)
    print(", ".join(stale), flush=True)
    return stale


def _remove_service_containers(services: list[str]) -> None:
    """Stop and remove containers by name (compose-managed or orphan)."""
    for service in services:
        subprocess.run(["docker", "stop", service], capture_output=True, text=True)
        subprocess.run(["docker", "rm", "-f", service], capture_output=True, text=True)


def _compose_cmd(*args: str, root: Path | None = None) -> list[str]:
    return ["docker", "compose", "-f", str((root or repo_root()) / "compose.yaml"), *args]


def run_compose(args: list[str], root: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = _compose_cmd(*args, root=root)
    return subprocess.run(cmd, cwd=root or repo_root(), check=check, text=True)


def up(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    args = ["up", "-d"]
    expanded: list[str] = []
    if services:
        expanded = expand_services(services, operation="up")
        args.extend(expanded)
    run_compose(args, root=root)
    if not services or "gluetun" in expanded or set(expanded) & set(_gluetun_sidecars()):
        sync_gluetun_sidecars(root=root)


def down(services: list[str] | None = None, root: Path | None = None) -> None:
    render_compose()
    if services:
        expanded = expand_services(services, operation="down")
        run_compose(["stop", *expanded], root=root, check=False)
        run_compose(["rm", "-f", *expanded], root=root, check=False)
        _remove_service_containers(expanded)
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
