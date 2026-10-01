"""Service registry — compose names, deploy playbooks, stack groups."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from homelab_cli.paths import services_registry

# Deploy order when running deploy --all (matches deploy-services.yml)
DEPLOY_ORDER: list[str] = [
    "socket-proxy",
    "watchtower",
    "dozzle",
    "traefik",
    "cloudflare-ddns",
    "authelia",
    "uptime-kuma",
    "autokuma",
    "memos",
    "audiobookshelf",
    "mealie",
    "paperless",
    "gluetun",
    "dispatcharr",
    "qbittorrent",
    "prowlarr",
    "sonarr",
    "radarr",
    "bazarr",
    "jellyfin",
    "jellyscope",
    "homepage",
]


def load_registry(path: Path | None = None) -> dict[str, Any]:
    reg_path = path or services_registry()
    with reg_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def expand_services(
    names: list[str],
    registry: dict[str, Any] | None = None,
    *,
    operation: str = "stop",
) -> list[str]:
    """Expand stack groups when starting; stop/down/restart only named services.

    Gluetun sidecars share `network_mode: service:gluetun`. Bringing up gluetun
    (or any sidecar) ensures the gateway is running; stopping one sidecar must not
    stop the whole VPN stack.
    """
    reg = registry or load_registry()
    stacks: dict[str, list[str]] = reg.get("stacks", {})
    services: dict[str, Any] = reg.get("services", {})
    expanded: list[str] = []
    seen: set[str] = set()

    def add(member: str) -> None:
        if member not in seen:
            seen.add(member)
            expanded.append(member)

    for name in names:
        stack_name = services.get(name, {}).get("stack")
        stack_members = stacks.get(stack_name, [name]) if stack_name else [name]

        if operation in ("stop", "down"):
            add(name)
        elif operation == "restart":
            if name == "gluetun" and stack_name:
                for member in stack_members:
                    add(member)
            else:
                add(name)
        elif operation in ("start", "up"):
            if name == "gluetun" and stack_name:
                for member in stack_members:
                    add(member)
            elif stack_name and "gluetun" in stack_members:
                add("gluetun")
                add(name)
            else:
                add(name)
        else:
            for member in stack_members:
                add(member)

    return expanded


def playbook_for_service(service: str, registry: dict[str, Any] | None = None) -> str | None:
    reg = registry or load_registry()
    svc = reg.get("services", {}).get(service, {})
    return svc.get("deploy_playbook")


def resolve_deploy_playbooks(
    names: list[str] | None = None,
    deploy_all: bool = False,
    registry: dict[str, Any] | None = None,
) -> list[str]:
    reg = registry or load_registry()
    services_map: dict[str, Any] = reg.get("services", {})

    if deploy_all:
        target_services = [s for s in DEPLOY_ORDER if s in services_map]
    elif names:
        target_services = names
    else:
        return []

    playbooks: list[str] = []
    seen_pb: set[str] = set()
    order_index = {s: i for i, s in enumerate(DEPLOY_ORDER)}

    def sort_key(svc: str) -> int:
        return order_index.get(svc, 999)

    for svc in sorted(set(target_services), key=sort_key):
        pb = playbook_for_service(svc, reg)
        if pb and pb not in seen_pb:
            seen_pb.add(pb)
            playbooks.append(pb)
    return playbooks


def all_compose_services(registry: dict[str, Any] | None = None) -> list[str]:
    reg = registry or load_registry()
    return list(reg.get("services", {}).keys())


def backupable_services(registry: dict[str, Any] | None = None) -> list[str]:
    """Services with backup: true in config/services.yaml (used by homelab backup --all)."""
    reg = registry or load_registry()
    services: dict[str, Any] = reg.get("services", {})
    return [name for name, svc in services.items() if svc.get("backup")]
