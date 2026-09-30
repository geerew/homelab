"""Show homelab container status."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from homelab_cli.docker import (
    _docker_inspect,
    _gluetun_sidecars,
    find_stale_gluetun_sidecars,
)
from homelab_cli.registry import all_compose_services, load_registry


@dataclass(frozen=True)
class ServiceStatus:
    name: str
    state: str
    health: str
    compose: bool
    network: str
    issue: str | None = None

    @property
    def ok(self) -> bool:
        return self.state == "running" and self.issue is None


def _network_summary(service: str, sidecars: set[str]) -> str:
    mode = _docker_inspect(service, "{{.HostConfig.NetworkMode}}") or "-"
    if service in sidecars and mode.startswith("container:"):
        return "gluetun"
    if mode == "default":
        return "bridge"
    return mode


def _service_issue(
    service: str,
    state: str,
    sidecars: set[str],
    stale_sidecars: set[str],
    compose_project: str | None,
) -> str | None:
    if state == "missing":
        return "container not found"
    if state != "running":
        return f"container {state}"
    if service in stale_sidecars:
        return "stale gluetun network — run: homelab up " + service
    if service in sidecars and not (_docker_inspect(service, "{{.HostConfig.NetworkMode}}") or "").startswith(
        "container:"
    ):
        return "not attached to gluetun"
    if not compose_project:
        return "orphan (not compose-managed)"
    return None


def collect_status(services: list[str] | None = None) -> list[ServiceStatus]:
    registry = load_registry()
    sidecars = set(_gluetun_sidecars(registry))
    stale_sidecars = set(find_stale_gluetun_sidecars(registry))
    names = services or all_compose_services(registry)

    rows: list[ServiceStatus] = []
    for name in names:
        state = _docker_inspect(name, "{{.State.Status}}") or "missing"
        health = _docker_inspect(
            name,
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}-{{end}}",
        ) or "-"
        compose_project = _docker_inspect(name, '{{index .Config.Labels "com.docker.compose.project"}}')
        rows.append(
            ServiceStatus(
                name=name,
                state=state,
                health=health,
                compose=bool(compose_project),
                network=_network_summary(name, sidecars) if state != "missing" else "-",
                issue=_service_issue(name, state, sidecars, stale_sidecars, compose_project),
            )
        )
    return rows


def _print_table(rows: list[ServiceStatus]) -> None:
    headers = ("SERVICE", "STATE", "HEALTH", "NETWORK", "ISSUE")
    widths = [
        max(len(headers[0]), *(len(row.name) for row in rows), 7),
        max(len(headers[1]), *(len(row.state) for row in rows), 5),
        max(len(headers[2]), *(len(row.health) for row in rows), 6),
        max(len(headers[3]), *(len(row.network) for row in rows), 7),
        max(len(headers[4]), *(len(row.issue or "-") for row in rows), 5),
    ]

    def fmt(cols: tuple[str, ...]) -> str:
        return "  ".join(col.ljust(widths[index]) for index, col in enumerate(cols))

    print(fmt(headers))
    print(fmt(tuple("-" * width for width in widths)))
    for row in rows:
        print(
            fmt(
                (
                    row.name,
                    row.state,
                    row.health,
                    row.network,
                    row.issue or "-",
                )
            )
        )


def run_status(services: list[str] | None = None, *, json_output: bool = False) -> int:
    rows = collect_status(services)

    if json_output:
        print(json.dumps([asdict(row) for row in rows], indent=2))
    else:
        _print_table(rows)
        running = sum(1 for row in rows if row.state == "running")
        issues = [row for row in rows if row.issue]
        print()
        print(f"{running}/{len(rows)} running", end="")
        if issues:
            print(f", {len(issues)} issue(s)")
        else:
            print(", all OK")

    return 1 if any(row.issue for row in rows) else 0
