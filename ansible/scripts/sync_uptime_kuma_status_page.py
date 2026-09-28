#!/usr/bin/env python3
"""Sync Uptime Kuma status page groups from a JSON config file."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from typing import Any

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://uptime-kuma:3001")
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--slug", default="default")
    parser.add_argument("--config", default=None, help="Path to status page JSON config")
    parser.add_argument(
        "--bootstrap-only",
        action="store_true",
        help="Only run first-time setup (create internal user, disable auth) and exit",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when configured monitors are missing in Kuma",
    )
    return parser.parse_args()


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def normalize_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for group in groups:
        monitor_ids = sorted(
            int(entry["id"])
            for entry in group.get("monitorList", [])
            if entry.get("id") is not None
        )
        normalized.append(
            {
                "name": group["name"],
                "weight": int(group.get("weight", 1000)),
                "monitor_ids": monitor_ids,
            }
        )
    return sorted(normalized, key=lambda item: (item["weight"], item["name"]))


def get_status_page(api: Any, slug: str) -> dict[str, Any]:
    """Uptime Kuma v2-compatible status page read (uptime-kuma-api get_status_page breaks on v2)."""
    socket_page = api._call("getStatusPage", slug)
    rest_page = requests.get(f"{api.url}/api/status-page/{slug}", timeout=api.timeout).json()
    config = {**socket_page.get("config", {}), **rest_page.get("config", {})}
    return {
        **config,
        "publicGroupList": rest_page.get("publicGroupList", []),
    }


def build_save_payload(
    status_page: dict[str, Any],
    slug: str,
    public_group_list: list[dict[str, Any]],
) -> tuple[str, dict[str, Any], str, list[dict[str, Any]]]:
    """Build a Kuma v2-compatible saveStatusPage payload (uptime-kuma-api is missing v2 fields)."""
    config = {
        "id": status_page["id"],
        "slug": slug,
        "title": status_page.get("title", slug),
        "description": status_page.get("description"),
        "theme": status_page.get("theme", "auto"),
        "published": status_page.get("published", True),
        "showTags": status_page.get("showTags", False),
        "domainNameList": status_page.get("domainNameList", []),
        "footerText": status_page.get("footerText"),
        "customCSS": status_page.get("customCSS", ""),
        "showPoweredBy": status_page.get("showPoweredBy", True),
        "showCertificateExpiry": status_page.get("showCertificateExpiry", False),
        "autoRefreshInterval": status_page.get("autoRefreshInterval", 300),
        "analyticsId": status_page.get("analyticsId"),
        "analyticsScriptUrl": status_page.get("analyticsScriptUrl"),
        # Must be null when unset — undefined triggers "Invalid analytics type" on Kuma v2.
        "analyticsType": status_page.get("analyticsType"),
        "rssTitle": status_page.get("rssTitle"),
        "showOnlyLastHeartbeat": status_page.get("showOnlyLastHeartbeat", False),
    }
    icon = status_page.get("icon", "/icon.svg")
    groups: list[dict[str, Any]] = []
    for group in public_group_list:
        entry: dict[str, Any] = {
            "name": group["name"],
            "weight": group.get("weight", 1000),
            "monitorList": [{"id": monitor["id"]} for monitor in group.get("monitorList", [])],
        }
        if group.get("id") is not None:
            entry["id"] = group["id"]
        groups.append(entry)
    return slug, config, icon, groups


def save_status_page(api: Any, slug: str, **kwargs: Any) -> dict[str, Any]:
    status_page = get_status_page(api, slug)
    status_page.update(kwargs)
    data = build_save_payload(
        status_page,
        slug,
        status_page.get("publicGroupList", []),
    )
    return api._call("saveStatusPage", data)


def build_public_group_list(
    desired_groups: list[dict[str, Any]],
    monitors_by_name: dict[str, int],
    existing_groups: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    existing_by_name = {
        group["name"]: group for group in (existing_groups or []) if group.get("name")
    }
    warnings: list[str] = []
    public_groups: list[dict[str, Any]] = []

    for desired in desired_groups:
        group_name = desired["name"]
        weight = int(desired.get("weight", 1000))
        monitor_names = desired.get("monitors", [])
        monitor_list: list[dict[str, int]] = []

        for monitor_name in monitor_names:
            monitor_id = monitors_by_name.get(monitor_name)
            if monitor_id is None:
                warnings.append(f"Monitor not found (Autokuma may still be syncing): {monitor_name}")
                continue
            monitor_list.append({"id": monitor_id})

        entry: dict[str, Any] = {
            "name": group_name,
            "weight": weight,
            "monitorList": monitor_list,
        }
        existing = existing_by_name.get(group_name)
        if existing and existing.get("id") is not None:
            entry["id"] = existing["id"]
        public_groups.append(entry)

    return public_groups, warnings


def bootstrap_if_needed(api: Any) -> bool:
    """First-time Kuma install: create an internal user and disable dashboard auth."""
    if not api.need_setup():
        return False

    bootstrap_password = secrets.token_urlsafe(24)
    api.setup("bootstrap", bootstrap_password)
    api.login("bootstrap", bootstrap_password)
    settings = api.get_settings()
    api.set_settings(
        password=bootstrap_password,
        disableAuth=True,
        checkUpdate=settings.get("checkUpdate", True),
        keepDataPeriodDays=settings.get("keepDataPeriodDays", 180),
        serverTimezone=settings.get("serverTimezone", ""),
        entryPage=settings.get("entryPage", "dashboard"),
        searchEngineIndex=settings.get("searchEngineIndex", False),
        trustProxy=settings.get("trustProxy", False),
        tlsExpiryNotifyDays=settings.get("tlsExpiryNotifyDays", [7, 14, 21]),
    )
    api.disconnect()
    api.connect()
    api.login()
    print("Bootstrapped Uptime Kuma (disableAuth=true; Authelia handles edge auth).")
    return True


def login(api: Any, username: str | None, password: str | None) -> None:
    if username and password:
        api.login(username, password)
        return
    api.login()


def connect_api(url: str, retries: int = 12, delay: float = 5.0) -> Any:
    from uptime_kuma_api import UptimeKumaApi
    from uptime_kuma_api.exceptions import UptimeKumaException

    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        api = UptimeKumaApi(url, timeout=20)
        try:
            return api
        except UptimeKumaException as exc:
            last_error = exc
            api.disconnect()
            if attempt < retries:
                print(
                    f"Waiting for Uptime Kuma API (attempt {attempt}/{retries})...",
                    file=sys.stderr,
                )
                time.sleep(delay)
    raise last_error or RuntimeError("unable to connect to Uptime Kuma")


def main() -> int:
    args = parse_args()

    try:
        from uptime_kuma_api import UptimeKumaApi
        from uptime_kuma_api.exceptions import UptimeKumaException
    except ImportError:
        print("uptime-kuma-api is required: pip install uptime-kuma-api", file=sys.stderr)
        return 2

    api = connect_api(args.url)
    try:
        bootstrapped = bootstrap_if_needed(api)
        if bootstrapped and args.bootstrap_only:
            return 0

        login(api, args.username, args.password)

        if args.bootstrap_only:
            print("Uptime Kuma already initialized.")
            return 0

        if not args.config:
            print("--config is required unless using --bootstrap-only", file=sys.stderr)
            return 2

        config = load_config(args.config)
        monitors = api.get_monitors()
        monitors_by_name = {monitor["name"]: monitor["id"] for monitor in monitors}

        try:
            current_page = get_status_page(api, args.slug)
        except UptimeKumaException:
            api.add_status_page(args.slug, config.get("title", args.slug))
            current_page = get_status_page(api, args.slug)

        desired_public_groups, warnings = build_public_group_list(
            config.get("groups", []),
            monitors_by_name,
            current_page.get("publicGroupList"),
        )

        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)

        current_normalized = normalize_groups(current_page.get("publicGroupList", []))
        desired_normalized = normalize_groups(desired_public_groups)

        if current_normalized == desired_normalized:
            print(f"Status page '{args.slug}' already matches desired layout.")
            return 2 if args.strict and warnings else 0

        save_status_page(
            api,
            args.slug,
            title=config.get("title", current_page.get("title", args.slug)),
            published=config.get("published", current_page.get("published", True)),
            publicGroupList=desired_public_groups,
            description=config.get("description", current_page.get("description")),
            theme=config.get("theme", current_page.get("theme")),
        )
        print(
            f"Updated status page '{args.slug}' "
            f"({len(desired_public_groups)} groups, {len(monitors_by_name)} monitors in Kuma)."
        )
        return 2 if args.strict and warnings else 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        api.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
