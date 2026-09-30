#!/usr/bin/env python3
"""Configure Radarr from homelab.yaml (idempotent)."""

from __future__ import annotations

import copy
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# Radarr is always behind Authelia at Traefik (Remote-User header).
AUTH_METHOD = "external"
DEFAULT_INDEXER_PRIORITY = 25
DEFAULT_DOWNLOAD_CLIENT = "qbittorrent"
SUPPORTED_DOWNLOAD_CLIENTS = frozenset({"qbittorrent", "qbit"})
LIBRARY_IMPORT_BATCH_SIZE = 100
LIBRARY_IMPORT_LOOKUP_WORKERS = 5
LIBRARY_IMPORT_ROOT_FOLDER_TIMEOUT = 600
DEFAULT_LIBRARY_IMPORT_QUALITY_PROFILE = "Any"
DEFAULT_LIBRARY_IMPORT_MONITOR = "none"
QUALITY_DEFINITION_TIERS: dict[str, list[str]] = {
    "720p": ["HDTV-720p", "WEBDL-720p", "WEBRip-720p", "Bluray-720p"],
    "1080p": ["HDTV-1080p", "WEBDL-1080p", "WEBRip-1080p", "Bluray-1080p"],
}


def log(msg: str) -> None:
    print(f"radarr bootstrap: {msg}", file=sys.stderr)


def snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def camel_dict(data: dict[str, Any]) -> dict[str, Any]:
    return {snake_to_camel(key): value for key, value in data.items()}


def normalize_config_keys(data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(data)
    chmod = normalized.get("chmodFolder") or normalized.get("chmod_folder")
    if chmod is not None and not isinstance(chmod, str):
        key = "chmodFolder" if "chmodFolder" in normalized else "chmod_folder"
        normalized[key] = str(chmod)
    return normalized


def parse_json(raw: bytes) -> Any:
    if not raw:
        return None
    return json.loads(raw)


def api_request(
    method: str,
    url: str,
    api_key: str,
    body: dict | list | None = None,
    timeout: float = 60,
) -> tuple[int, Any]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Api-Key": api_key,
    }
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, parse_json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, parse_json(exc.read())


def read_api_key(config_xml: Path) -> str:
    if not config_xml.is_file():
        raise RuntimeError(f"config.xml not found: {config_xml}")
    root = ET.parse(config_xml).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"No ApiKey in {config_xml}")
    return api_key.strip()


def wait_for_api(base: str, api_key: str, retries: int = 24, delay: float = 5.0) -> None:
    for attempt in range(1, retries + 1):
        status, _payload = api_request("GET", f"{base}/ping", api_key)
        if status == 200:
            return
        log(f"waiting for Radarr API ({attempt}/{retries})")
        time.sleep(delay)
    raise RuntimeError(f"Radarr API not ready at {base}/ping")


def load_json_env(name: str, default: Any) -> Any:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return json.loads(raw)


def field_value(fields: list[dict[str, Any]], name: str) -> Any:
    for field in fields:
        if field.get("name") == name:
            return field.get("value")
    return None


def set_field_value(fields: list[dict[str, Any]], name: str, value: Any) -> None:
    for field in fields:
        if field.get("name") == name:
            field["value"] = value
            return
    raise RuntimeError(f"field '{name}' not found in schema")


def collect_allowed_names(items: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in items:
        quality = item.get("quality")
        if quality and item.get("allowed"):
            names.add(str(quality.get("name", "")))
        elif item.get("items") is not None:
            names.update(collect_allowed_names(item["items"]))
    return {name for name in names if name}


def find_quality_id(items: list[dict[str, Any]], name: str) -> int | None:
    for item in items:
        quality = item.get("quality")
        if quality and quality.get("name") == name:
            quality_id = quality.get("id")
            return int(quality_id) if quality_id is not None else None
        if item.get("items") is not None:
            found = find_quality_id(item["items"], name)
            if found is not None:
                return found
    return None


def apply_allowed_qualities(items: list[dict[str, Any]], allowed: set[str]) -> None:
    for item in items:
        quality = item.get("quality")
        if quality:
            if item.get("items") in ("", None):
                item["items"] = []
            item["allowed"] = quality.get("name") in allowed
        elif item.get("items") is not None:
            apply_allowed_qualities(item["items"], allowed)
            item["allowed"] = any(child.get("allowed") for child in item["items"])


def profile_template_items(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for profile in profiles:
        if profile.get("name") == "Any" and profile.get("items"):
            return copy.deepcopy(profile["items"])
    for profile in profiles:
        if profile.get("items"):
            return copy.deepcopy(profile["items"])
    raise RuntimeError("no quality profile template found in Radarr")


def default_profile_metadata(reference: dict[str, Any]) -> dict[str, Any]:
    return {
        "minFormatScore": reference.get("minFormatScore", 0),
        "cutoffFormatScore": reference.get("cutoffFormatScore", 0),
        "minUpgradeFormatScore": reference.get("minUpgradeFormatScore", 1),
        "formatItems": reference.get("formatItems", []),
        "language": reference.get("language", {"id": 1, "name": "English"}),
    }


def build_quality_profile_payload(
    template_items: list[dict[str, Any]],
    desired: dict[str, Any],
    global_qualities: dict[str, bool],
    existing: dict[str, Any] | None = None,
    reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = desired["name"]
    cutoff_name = desired.get("cutoff")
    if not cutoff_name:
        raise RuntimeError(f"quality profile '{name}' requires cutoff (quality name)")

    profile_qualities = desired.get("qualities") or desired.get("allowed") or []
    if not profile_qualities:
        raise RuntimeError(f"quality profile '{name}' requires qualities list")

    allowed = set(profile_qualities)
    for quality_name, enabled in global_qualities.items():
        if not enabled:
            allowed.discard(quality_name)

    items = copy.deepcopy(existing["items"] if existing else template_items)
    apply_allowed_qualities(items, allowed)

    cutoff_id = find_quality_id(items, cutoff_name)
    if cutoff_id is None:
        raise RuntimeError(
            f"cutoff quality '{cutoff_name}' not found for profile '{name}'"
        )

    meta_source = existing or reference or {}
    return {
        "name": name,
        "upgradeAllowed": desired.get("upgrade", desired.get("upgradeAllowed", False)),
        "cutoff": cutoff_id,
        "items": items,
        **default_profile_metadata(meta_source),
    }


def profile_matches_desired(
    existing: dict[str, Any],
    desired: dict[str, Any],
    template_items: list[dict[str, Any]],
    global_qualities: dict[str, bool],
) -> bool:
    payload = build_quality_profile_payload(
        template_items, desired, global_qualities, existing=existing
    )
    if existing.get("upgradeAllowed") != payload["upgradeAllowed"]:
        return False
    if existing.get("cutoff") != payload["cutoff"]:
        return False
    return collect_allowed_names(existing.get("items", [])) == collect_allowed_names(
        payload["items"]
    )


def default_torznab_categories(torznab_schema: dict[str, Any]) -> list[int]:
    for field in torznab_schema.get("fields", []):
        if field.get("name") == "categories" and field.get("value"):
            return [int(value) for value in field["value"]]
    return [2000, 2010, 2020, 2030, 2040, 2045, 2050, 2060]


def normalize_indexer_entry(entry: str | dict[str, Any]) -> dict[str, Any]:
    """Accept a Prowlarr indexer name (string) or {name?, prowlarr_indexer}."""
    if isinstance(entry, str):
        prowlarr_name = entry.strip()
        if not prowlarr_name:
            raise RuntimeError("empty radarr indexer entry")
        return {
            "prowlarr_indexer": prowlarr_name,
            "name": f"{prowlarr_name} (Prowlarr)",
        }

    if not isinstance(entry, dict):
        raise RuntimeError(f"invalid radarr indexer entry: {entry!r}")

    prowlarr_name = str(entry.get("prowlarr_indexer", "")).strip()
    if not prowlarr_name:
        raise RuntimeError("radarr indexer entry missing prowlarr_indexer")

    normalized = copy.deepcopy(entry)
    normalized["prowlarr_indexer"] = prowlarr_name
    normalized["name"] = str(entry.get("name") or f"{prowlarr_name} (Prowlarr)").strip()
    return normalized


def normalize_indexers(entries: list[Any]) -> list[dict[str, Any]]:
    return [normalize_indexer_entry(entry) for entry in entries]


def normalize_download_client_entry(entry: str | dict[str, Any]) -> dict[str, Any]:
    """Accept 'qbittorrent' (string) or optional overrides as a dict."""
    if isinstance(entry, str):
        client = entry.strip().lower()
        if client not in SUPPORTED_DOWNLOAD_CLIENTS:
            raise RuntimeError(
                f"unsupported download client '{entry}' — only qbittorrent is supported"
            )
        entry = {}

    if not isinstance(entry, dict):
        raise RuntimeError(f"invalid download client entry: {entry!r}")

    qb_port = int(os.environ.get("QBITTORRENT_WEBUI_PORT", "8080"))
    return {
        "name": entry.get("name", "qBittorrent"),
        "implementation": entry.get("implementation", "QBittorrent"),
        "enable": entry.get("enable", True),
        "priority": entry.get("priority", 1),
        "remove_completed_downloads": entry.get("remove_completed_downloads", True),
        "remove_failed_downloads": entry.get("remove_failed_downloads", True),
        "host": entry.get("host", "localhost"),
        "port": entry.get("port", qb_port),
        "use_ssl": entry.get("use_ssl", False),
        "movie_category": entry.get("movie_category", "radarr"),
    }


def normalize_download_clients(entries: list[Any] | None) -> list[dict[str, Any]]:
    if not entries:
        return [normalize_download_client_entry(DEFAULT_DOWNLOAD_CLIENT)]
    return [normalize_download_client_entry(entry) for entry in entries]


def prowlarr_indexer_map(base: str, api_key: str) -> dict[str, int]:
    status, indexers = api_request("GET", f"{base}/api/v1/indexer", api_key)
    if status != 200 or not isinstance(indexers, list):
        raise RuntimeError(f"failed to list Prowlarr indexers ({status}): {indexers}")
    return {item["name"]: int(item["id"]) for item in indexers if item.get("name") and item.get("id")}


def ensure_auth(base: str, api_key: str) -> bool:
    status, host = api_request("GET", f"{base}/api/v3/config/host", api_key)
    if status != 200 or not isinstance(host, dict):
        raise RuntimeError(f"failed to read host config ({status}): {host}")

    if host.get("authenticationMethod") == AUTH_METHOD:
        return False

    desired = copy.deepcopy(host)
    desired["authenticationMethod"] = AUTH_METHOD
    status, result = api_request("PUT", f"{base}/api/v3/config/host", api_key, desired)
    if status >= 400:
        raise RuntimeError(f"failed to update host config ({status}): {result}")
    log(f"updated auth method to {AUTH_METHOD}")
    return True


def ensure_root_folders(base: str, api_key: str, desired_paths: list[str]) -> bool:
    if not desired_paths:
        return False

    status, existing_list = api_request("GET", f"{base}/api/v3/rootfolder", api_key)
    if status != 200 or not isinstance(existing_list, list):
        raise RuntimeError(f"failed to list root folders ({status}): {existing_list}")

    existing_paths = {item.get("path") for item in existing_list}
    changed = False
    for path in desired_paths:
        if path in existing_paths:
            log(f"root folder unchanged: {path}")
            continue
        status, result = api_request("POST", f"{base}/api/v3/rootfolder", api_key, {"path": path})
        if status >= 400:
            raise RuntimeError(f"failed to add root folder '{path}' ({status}): {result}")
        log(f"added root folder: {path}")
        changed = True
    return changed


def indexer_needs_update(
    existing: dict[str, Any],
    desired: dict[str, Any],
    base_url: str,
    categories: list[int],
) -> bool:
    checks = (
        ("enableRss", desired.get("enable_rss", True)),
        ("enableAutomaticSearch", desired.get("enable_automatic_search", True)),
        ("enableInteractiveSearch", desired.get("enable_interactive_search", True)),
        ("priority", desired.get("priority", 25)),
    )
    for key, expected in checks:
        if existing.get(key) != expected:
            return True
    if field_value(existing.get("fields", []), "baseUrl") != base_url:
        return True
    existing_categories = field_value(existing.get("fields", []), "categories") or []
    if sorted(existing_categories) != sorted(categories):
        return True
    return False


def ensure_indexers(
    base: str,
    api_key: str,
    desired_indexers: list[Any],
    prowlarr_base: str,
    prowlarr_api_key: str,
) -> bool:
    if not desired_indexers:
        return False

    indexers = normalize_indexers(desired_indexers)
    prowlarr_ids = prowlarr_indexer_map(prowlarr_base, prowlarr_api_key)

    status, existing_list = api_request("GET", f"{base}/api/v3/indexer", api_key)
    if status != 200 or not isinstance(existing_list, list):
        raise RuntimeError(f"failed to list indexers ({status}): {existing_list}")

    status, schema_list = api_request("GET", f"{base}/api/v3/indexer/schema", api_key)
    if status != 200 or not isinstance(schema_list, list):
        raise RuntimeError(f"failed to load indexer schema ({status}): {schema_list}")

    torznab_schema = next(
        (item for item in schema_list if item.get("implementation") == "Torznab"),
        None,
    )
    if not torznab_schema:
        raise RuntimeError("Torznab indexer schema not found in Radarr")

    default_categories = default_torznab_categories(torznab_schema)
    existing_by_name = {item["name"]: item for item in existing_list}
    changed = False

    for desired in indexers:
        name = desired["name"]
        prowlarr_name = desired["prowlarr_indexer"]
        if prowlarr_name not in prowlarr_ids:
            known = ", ".join(sorted(prowlarr_ids)) or "(none)"
            raise RuntimeError(
                f"Prowlarr indexer '{prowlarr_name}' not found — deploy prowlarr first "
                f"(available: {known})"
            )

        prowlarr_id = prowlarr_ids[prowlarr_name]
        base_url = f"http://localhost:{os.environ.get('PROWLARR_PORT', '9696')}/{prowlarr_id}/"
        categories = desired.get("categories") or default_categories

        existing = existing_by_name.get(name)
        if existing and not indexer_needs_update(existing, desired, base_url, categories):
            log(f"indexer unchanged: {name}")
            continue

        payload = copy.deepcopy(existing if existing else torznab_schema)
        payload["name"] = name
        payload["implementation"] = "Torznab"
        payload["configContract"] = torznab_schema.get("configContract", "TorznabSettings")
        payload["enableRss"] = desired.get("enable_rss", True)
        payload["enableAutomaticSearch"] = desired.get("enable_automatic_search", True)
        payload["enableInteractiveSearch"] = desired.get("enable_interactive_search", True)
        payload["priority"] = desired.get("priority", DEFAULT_INDEXER_PRIORITY)

        fields = payload.get("fields", [])
        set_field_value(fields, "baseUrl", base_url)
        set_field_value(fields, "apiPath", "/api")
        set_field_value(fields, "apiKey", prowlarr_api_key)
        set_field_value(fields, "categories", categories)
        payload["fields"] = fields

        if existing:
            payload["id"] = existing["id"]
            status, result = api_request(
                "PUT", f"{base}/api/v3/indexer/{existing['id']}", api_key, payload
            )
            action = "updated"
        else:
            payload.pop("id", None)
            status, result = api_request("POST", f"{base}/api/v3/indexer", api_key, payload)
            action = "created"

        if status >= 400:
            raise RuntimeError(f"failed to {action[:-1]} indexer '{name}' ({status}): {result}")
        log(f"{action} indexer: {name} → {base_url}")
        changed = True

    return changed


def download_client_needs_update(
    existing: dict[str, Any],
    desired: dict[str, Any],
    username: str,
    password: str,
) -> bool:
    checks = (
        ("enable", desired.get("enable", True)),
        ("priority", desired.get("priority", 1)),
        ("removeCompletedDownloads", desired.get("remove_completed_downloads", True)),
        ("removeFailedDownloads", desired.get("remove_failed_downloads", True)),
    )
    for key, expected in checks:
        if existing.get(key) != expected:
            return True

    field_checks = {
        "host": desired.get("host", "localhost"),
        "port": desired.get("port", 8080),
        "useSsl": desired.get("use_ssl", False),
        "movieCategory": desired.get("movie_category", "radarr"),
        "username": username,
    }
    fields = existing.get("fields", [])
    for field_name, expected in field_checks.items():
        if field_value(fields, field_name) != expected:
            return True

    if password:
        existing_password = field_value(fields, "password")
        if existing_password not in ("", "********") and existing_password != password:
            return True
    return False


def ensure_download_clients(
    base: str,
    api_key: str,
    desired_clients: list[Any] | None,
    username: str,
    password: str,
) -> bool:
    clients = normalize_download_clients(desired_clients)

    status, existing_list = api_request("GET", f"{base}/api/v3/downloadclient", api_key)
    if status != 200 or not isinstance(existing_list, list):
        raise RuntimeError(f"failed to list download clients ({status}): {existing_list}")

    status, schema_list = api_request("GET", f"{base}/api/v3/downloadclient/schema", api_key)
    if status != 200 or not isinstance(schema_list, list):
        raise RuntimeError(f"failed to load download client schema ({status}): {schema_list}")

    schema_by_impl = {item["implementation"]: item for item in schema_list}
    existing_by_name = {item["name"]: item for item in existing_list}
    changed = False

    for desired in clients:
        name = desired["name"]
        implementation = desired["implementation"]
        if implementation not in schema_by_impl:
            raise RuntimeError(f"unknown download client implementation '{implementation}'")

        existing = existing_by_name.get(name)
        if existing and not download_client_needs_update(existing, desired, username, password):
            log(f"download client unchanged: {name}")
            continue

        payload = copy.deepcopy(existing if existing else schema_by_impl[implementation])
        payload["name"] = name
        payload["implementation"] = implementation
        payload["enable"] = desired.get("enable", True)
        payload["priority"] = desired.get("priority", 1)
        payload["removeCompletedDownloads"] = desired.get("remove_completed_downloads", True)
        payload["removeFailedDownloads"] = desired.get("remove_failed_downloads", True)

        fields = payload.get("fields", [])
        set_field_value(fields, "host", desired.get("host", "localhost"))
        set_field_value(fields, "port", desired.get("port", 8080))
        set_field_value(fields, "useSsl", desired.get("use_ssl", False))
        if username:
            set_field_value(fields, "username", username)
        if password:
            set_field_value(fields, "password", password)
        set_field_value(fields, "movieCategory", desired.get("movie_category", "radarr"))
        payload["fields"] = fields

        if existing:
            payload["id"] = existing["id"]
            status, result = api_request(
                "PUT",
                f"{base}/api/v3/downloadclient/{existing['id']}",
                api_key,
                payload,
            )
            action = "updated"
        else:
            payload.pop("id", None)
            status, result = api_request("POST", f"{base}/api/v3/downloadclient", api_key, payload)
            action = "created"

        if status >= 400:
            raise RuntimeError(
                f"failed to {action[:-1]} download client '{name}' ({status}): {result}"
            )
        log(f"{action} download client: {name}")
        changed = True

    return changed


def config_needs_update(existing: dict[str, Any], desired: dict[str, Any]) -> bool:
    for key, value in desired.items():
        if key == "id":
            continue
        if existing.get(key) != value:
            return True
    return False


def ensure_config_section(
    base: str,
    api_key: str,
    section: str,
    desired_raw: dict[str, Any],
) -> bool:
    if not desired_raw:
        return False

    desired = normalize_config_keys(camel_dict(desired_raw))
    status, existing = api_request("GET", f"{base}/api/v3/config/{section}", api_key)
    if status != 200 or not isinstance(existing, dict):
        raise RuntimeError(f"failed to read {section} config ({status}): {existing}")

    if not config_needs_update(existing, desired):
        log(f"{section} config unchanged")
        return False

    payload = copy.deepcopy(existing)
    payload.update(desired)
    status, result = api_request("PUT", f"{base}/api/v3/config/{section}", api_key, payload)
    if status >= 400:
        raise RuntimeError(f"failed to update {section} config ({status}): {result}")
    log(f"updated {section} config")
    return True


def ensure_quality_profiles(
    base: str,
    api_key: str,
    desired_profiles: list[dict[str, Any]],
    global_qualities: dict[str, bool] | None = None,
) -> bool:
    if not desired_profiles:
        return False

    overrides = global_qualities or {}
    status, existing_list = api_request("GET", f"{base}/api/v3/qualityprofile", api_key)
    if status != 200 or not isinstance(existing_list, list):
        raise RuntimeError(f"failed to list quality profiles ({status}): {existing_list}")

    template_items = profile_template_items(existing_list)
    reference_profile = next(
        (item for item in existing_list if item.get("name") == "Any"),
        existing_list[0],
    )
    existing_by_name = {item["name"]: item for item in existing_list if item.get("name")}
    changed = False

    for desired in desired_profiles:
        name = desired.get("name")
        if not name:
            continue

        existing = existing_by_name.get(name)
        if existing and profile_matches_desired(
            existing, desired, template_items, overrides
        ):
            log(f"quality profile unchanged: {name}")
            continue

        payload = build_quality_profile_payload(
            template_items,
            desired,
            overrides,
            existing=existing,
            reference=reference_profile,
        )
        if existing:
            payload["id"] = existing["id"]
            status, result = api_request(
                "PUT",
                f"{base}/api/v3/qualityprofile/{existing['id']}",
                api_key,
                payload,
            )
            action = "updated"
        else:
            status, result = api_request("POST", f"{base}/api/v3/qualityprofile", api_key, payload)
            action = "created"

        if status >= 400:
            raise RuntimeError(
                f"failed to {action[:-1]} quality profile '{name}' ({status}): {result}"
            )
        log(f"{action} quality profile: {name}")
        changed = True

    return changed


def expand_quality_definitions(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expanded: dict[str, dict[str, Any]] = {}
    for key, value in config.items():
        if not isinstance(value, dict):
            raise RuntimeError(f"quality_definitions entry '{key}' must be a mapping")
        tier_qualities = QUALITY_DEFINITION_TIERS.get(key)
        if tier_qualities:
            for quality_name in tier_qualities:
                expanded[quality_name] = value
        else:
            expanded[key] = value
    return expanded


def quality_definition_sizes(settings: dict[str, Any]) -> tuple[float, float, float]:
    min_size = settings.get("min", settings.get("min_size"))
    preferred = settings.get("preferred", settings.get("preferred_size"))
    max_size = settings.get("max", settings.get("max_size"))
    if min_size is None or preferred is None or max_size is None:
        raise RuntimeError(
            "quality_definitions entries require min, preferred, and max (MB/min)"
        )
    return float(min_size), float(preferred), float(max_size)


def ensure_quality_definitions(
    base: str,
    api_key: str,
    desired_raw: dict[str, Any],
) -> bool:
    if not desired_raw:
        return False

    desired = expand_quality_definitions(desired_raw)
    status, existing_list = api_request("GET", f"{base}/api/v3/qualitydefinition", api_key)
    if status != 200 or not isinstance(existing_list, list):
        raise RuntimeError(f"failed to list quality definitions ({status}): {existing_list}")

    by_name = {
        item["quality"]["name"]: item
        for item in existing_list
        if item.get("quality", {}).get("name")
    }
    to_update: list[dict[str, Any]] = []

    for quality_name, settings in desired.items():
        existing = by_name.get(quality_name)
        if not existing:
            log(f"quality definition skipped (unknown quality): {quality_name}")
            continue

        min_size, preferred, max_size = quality_definition_sizes(settings)
        if not (min_size < preferred < max_size):
            raise RuntimeError(
                f"quality definition '{quality_name}' requires min < preferred < max"
            )

        if (
            existing.get("minSize") == min_size
            and existing.get("preferredSize") == preferred
            and existing.get("maxSize") == max_size
        ):
            continue

        payload = copy.deepcopy(existing)
        payload["minSize"] = min_size
        payload["preferredSize"] = preferred
        payload["maxSize"] = max_size
        to_update.append(payload)

    if not to_update:
        log("quality definitions unchanged")
        return False

    status, result = api_request(
        "PUT",
        f"{base}/api/v3/qualitydefinition/update",
        api_key,
        to_update,
    )
    if status >= 400:
        raise RuntimeError(f"failed to update quality definitions ({status}): {result}")

    for item in to_update:
        log(f"updated quality definition: {item['quality']['name']}")
    return True


def resolve_quality_profile_id(
    base: str,
    api_key: str,
    profile_name: str,
) -> int:
    status, profiles = api_request("GET", f"{base}/api/v3/qualityprofile", api_key)
    if status != 200 or not isinstance(profiles, list) or not profiles:
        raise RuntimeError(f"failed to list quality profiles ({status}): {profiles}")

    lookup_name = profile_name.strip() or DEFAULT_LIBRARY_IMPORT_QUALITY_PROFILE

    for profile in profiles:
        if profile.get("name") == lookup_name:
            return int(profile["id"])

    known = ", ".join(sorted(str(p.get("name", "")) for p in profiles if p.get("name")))
    raise RuntimeError(
        f"quality profile '{lookup_name}' not found for library import (available: {known})"
    )


def fetch_existing_tmdb_ids(base: str, api_key: str) -> set[int]:
    status, movies = api_request("GET", f"{base}/api/v3/movie", api_key)
    if status != 200 or not isinstance(movies, list):
        raise RuntimeError(f"failed to list movies ({status}): {movies}")
    return {int(movie["tmdbId"]) for movie in movies if movie.get("tmdbId") is not None}


def fetch_unmapped_folders(base: str, api_key: str) -> list[tuple[str, str, str]]:
    status, root_folders = api_request("GET", f"{base}/api/v3/rootfolder", api_key)
    if status != 200 or not isinstance(root_folders, list):
        raise RuntimeError(f"failed to list root folders ({status}): {root_folders}")

    unmapped: list[tuple[str, str, str]] = []
    for root in root_folders:
        root_id = root.get("id")
        root_path = root.get("path")
        if root_id is None or not root_path:
            continue

        query = urllib.parse.urlencode({"timeout": "false"})
        status, details = api_request(
            "GET",
            f"{base}/api/v3/rootfolder/{root_id}?{query}",
            api_key,
            timeout=LIBRARY_IMPORT_ROOT_FOLDER_TIMEOUT,
        )
        if status != 200 or not isinstance(details, dict):
            raise RuntimeError(
                f"failed to fetch root folder '{root_path}' ({status}): {details}"
            )

        folders = details.get("unmappedFolders") or []
        log(f"library import: {len(folders)} unmapped folder(s) under {root_path}")
        for folder in folders:
            name = folder.get("name")
            path = folder.get("path")
            if name and path:
                unmapped.append((name, path, root_path))

    return unmapped


def lookup_movie_for_folder(base: str, api_key: str, folder_name: str) -> dict[str, Any] | None:
    # Match Radarr UI: skip short terms and use the first lookup result.
    if len(folder_name.strip()) <= 2:
        return None

    query = urllib.parse.urlencode({"term": folder_name})
    status, results = api_request("GET", f"{base}/api/v3/movie/lookup?{query}", api_key)
    if status != 200 or not isinstance(results, list) or not results:
        return None
    return results[0]


def build_import_payload(
    lookup: dict[str, Any],
    folder_path: str,
    root_folder_path: str,
    quality_profile_id: int,
    minimum_availability: str,
    monitor: str,
) -> dict[str, Any]:
    payload = copy.deepcopy(lookup)
    payload["path"] = folder_path
    payload["rootFolderPath"] = root_folder_path
    payload["qualityProfileId"] = quality_profile_id
    payload["minimumAvailability"] = minimum_availability
    payload["monitored"] = monitor != "none"
    payload["addOptions"] = {
        "monitor": monitor,
        "searchForMovie": False,
    }
    payload.pop("id", None)
    return payload


def lookup_unmapped_folder(
    base: str,
    api_key: str,
    folder_name: str,
    folder_path: str,
    root_path: str,
    quality_profile_id: int,
    minimum_availability: str,
    monitor: str,
    existing_tmdb: set[int],
) -> tuple[dict[str, Any] | None, str | None]:
    candidate = lookup_movie_for_folder(base, api_key, folder_name)
    if not candidate:
        return None, "no match"

    tmdb_id = candidate.get("tmdbId")
    if tmdb_id is None:
        return None, "no tmdbId"

    tmdb_id = int(tmdb_id)
    if tmdb_id in existing_tmdb:
        return None, "already in library"

    return (
        build_import_payload(
            candidate,
            folder_path,
            root_path,
            quality_profile_id,
            minimum_availability,
            monitor,
        ),
        None,
    )


def ensure_library_import(
    base: str,
    api_key: str,
    settings: dict[str, Any],
) -> bool:
    if not settings.get("enabled", True):
        log("library import disabled")
        return False

    quality_profile_id = resolve_quality_profile_id(
        base,
        api_key,
        str(settings.get("quality_profile", "")),
    )
    minimum_availability = str(settings.get("minimum_availability", "released"))
    monitor = str(settings.get("monitor", DEFAULT_LIBRARY_IMPORT_MONITOR))

    unmapped = fetch_unmapped_folders(base, api_key)
    if not unmapped:
        log("library import: no unmapped folders")
        return False

    existing_tmdb = fetch_existing_tmdb_ids(base, api_key)
    log(
        f"library import: {len(unmapped)} unmapped folder(s), "
        f"{len(existing_tmdb)} already in library"
    )

    matched: list[dict[str, Any]] = []
    skipped = 0
    processed = 0

    with ThreadPoolExecutor(max_workers=LIBRARY_IMPORT_LOOKUP_WORKERS) as executor:
        futures = {
            executor.submit(
                lookup_unmapped_folder,
                base,
                api_key,
                folder_name,
                folder_path,
                root_path,
                quality_profile_id,
                minimum_availability,
                monitor,
                existing_tmdb,
            ): folder_name
            for folder_name, folder_path, root_path in unmapped
        }

        for future in as_completed(futures):
            folder_name = futures[future]
            processed += 1
            if processed % 50 == 0 or processed == len(unmapped):
                log(f"library import: looked up {processed}/{len(unmapped)}")

            payload, skip_reason = future.result()
            if payload is None:
                skipped += 1
                if skip_reason == "no match":
                    log(f"library import skip (no match): {folder_name}")
                continue
            matched.append(payload)

    seen_tmdb: set[int] = set()
    payloads: list[dict[str, Any]] = []
    for payload in matched:
        tmdb_id = payload.get("tmdbId")
        if tmdb_id is None:
            continue
        tmdb_id = int(tmdb_id)
        if tmdb_id in seen_tmdb:
            skipped += 1
            continue
        seen_tmdb.add(tmdb_id)
        payloads.append(payload)

    if not payloads:
        log(f"library import: nothing to import ({skipped} skipped)")
        return False

    log(f"library import: importing {len(payloads)} movie(s)")
    imported = 0
    for offset in range(0, len(payloads), LIBRARY_IMPORT_BATCH_SIZE):
        batch = payloads[offset : offset + LIBRARY_IMPORT_BATCH_SIZE]
        status, result = api_request("POST", f"{base}/api/v3/movie/import", api_key, batch)
        if status >= 400:
            raise RuntimeError(f"failed to import movies ({status}): {result}")
        if isinstance(result, list):
            imported += len(result)
        else:
            imported += len(batch)
        log(f"library import: imported {imported}/{len(payloads)}")

    if skipped:
        log(f"library import: skipped {skipped} folder(s)")
    return True


def main() -> int:
    base = os.environ.get("RADARR_URL", "http://127.0.0.1:7878").rstrip("/")
    radarr_config = Path(
        os.environ.get("RADARR_CONFIG_XML", "services/radarr/config/config.xml")
    )
    prowlarr_base = os.environ.get("PROWLARR_URL", "http://127.0.0.1:9696").rstrip("/")
    prowlarr_config = Path(
        os.environ.get("PROWLARR_CONFIG_XML", "services/prowlarr/config/config.xml")
    )

    radarr_api_key = os.environ.get("RADARR_API_KEY", "").strip() or read_api_key(radarr_config)
    prowlarr_api_key = os.environ.get("PROWLARR_API_KEY", "").strip() or read_api_key(prowlarr_config)

    root_folders = load_json_env("RADARR_ROOT_FOLDERS", [])
    indexers = load_json_env("RADARR_INDEXERS", [])
    download_clients = load_json_env("RADARR_DOWNLOAD_CLIENTS", [])
    naming = load_json_env("RADARR_NAMING", {})
    media_management = load_json_env("RADARR_MEDIA_MANAGEMENT", {})
    quality_profiles = load_json_env("RADARR_QUALITY_PROFILES", [])
    quality_overrides = load_json_env("RADARR_QUALITIES", {})
    quality_definitions = load_json_env("RADARR_QUALITY_DEFINITIONS", {})
    library_import = load_json_env("RADARR_LIBRARY_IMPORT", {})

    qb_username = os.environ.get("QBITTORRENT_WEBUI_USERNAME", "")
    qb_password = os.environ.get("QBITTORRENT_WEBUI_PASSWORD", "")

    wait_for_api(base, radarr_api_key)

    changed = False
    changed |= ensure_auth(base, radarr_api_key)
    changed |= ensure_root_folders(base, radarr_api_key, root_folders)
    changed |= ensure_indexers(base, radarr_api_key, indexers, prowlarr_base, prowlarr_api_key)
    changed |= ensure_download_clients(
        base, radarr_api_key, download_clients, qb_username, qb_password
    )
    changed |= ensure_config_section(base, radarr_api_key, "naming", naming)
    changed |= ensure_config_section(base, radarr_api_key, "mediamanagement", media_management)
    changed |= ensure_quality_profiles(
        base, radarr_api_key, quality_profiles, quality_overrides
    )
    changed |= ensure_quality_definitions(base, radarr_api_key, quality_definitions)
    changed |= ensure_library_import(base, radarr_api_key, library_import)

    if not changed:
        log("nothing to change")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
