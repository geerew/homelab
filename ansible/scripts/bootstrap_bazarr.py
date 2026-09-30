#!/usr/bin/env python3
"""Configure Bazarr from homelab.yaml (idempotent)."""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml


def log(msg: str) -> None:
    print(f"bazarr bootstrap: {msg}", file=sys.stderr)


def read_api_key(config_xml: Path) -> str:
    if not config_xml.is_file():
        raise RuntimeError(f"config.xml not found: {config_xml}")
    root = ET.parse(config_xml).getroot()
    api_key = root.findtext("ApiKey")
    if not api_key:
        raise RuntimeError(f"No ApiKey in {config_xml}")
    return api_key.strip()


def load_json_env(name: str, default: Any) -> Any:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return json.loads(raw)


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"config not found: {path}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"invalid config at {path}")
    return data


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, default_flow_style=False, sort_keys=False)


def api_request(
    method: str,
    url: str,
    api_key: str,
    form: dict[str, str] | None = None,
) -> tuple[int, str]:
    headers = {"X-Api-Key": api_key}
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    if form is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def wait_for_api(base: str, api_key: str, retries: int = 24, delay: float = 5.0) -> None:
    for attempt in range(1, retries + 1):
        status, _ = api_request("GET", f"{base}/api/system/status", api_key)
        if status == 200:
            return
        log(f"waiting for Bazarr API ({attempt}/{retries})")
        import time

        time.sleep(delay)
    raise RuntimeError(f"Bazarr API not ready at {base}/api/system/status")


def deep_merge_dict(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def apply_auth(config: dict[str, Any], auth_setting: Any) -> bool:
    auth = config.setdefault("auth", {})
    desired_type = None if auth_setting in (None, "none", "") else auth_setting
    if auth.get("type") == desired_type:
        return False
    auth["type"] = desired_type
    log(f"updated auth type: {desired_type!r}")
    return True


def apply_arr_connection(
    config: dict[str, Any],
    section: str,
    enabled: bool,
    api_key: str,
    port: int,
) -> bool:
    block = config.setdefault(section, {})
    general = config.setdefault("general", {})
    use_key = f"use_{section}"
    desired = {
        "ip": "127.0.0.1",
        "port": port,
        "apikey": api_key,
        "ssl": False,
        "base_url": "",
    }
    changed = False
    if general.get(use_key) != enabled:
        general[use_key] = enabled
        changed = True
    for key, value in desired.items():
        if block.get(key) != value:
            block[key] = value
            changed = True
    if changed:
        log(f"updated {section} connection")
    return changed


def apply_providers(config: dict[str, Any], providers: dict[str, Any]) -> bool:
    if not providers:
        return False

    changed = False
    enabled = providers.get("enabled") or []
    general = config.setdefault("general", {})
    if general.get("enabled_providers") != enabled:
        general["enabled_providers"] = enabled
        changed = True
        log(f"updated enabled providers: {', '.join(enabled)}")

    for provider_name, settings in providers.items():
        if provider_name == "enabled" or not isinstance(settings, dict):
            continue
        block = config.setdefault(provider_name, {})
        merged = deep_merge_dict(block, settings)
        if merged != block:
            config[provider_name] = merged
            changed = True
            log(f"updated provider: {provider_name}")

    return changed


def profile_items(languages: list[str]) -> list[dict[str, str]]:
    return [
        {
            "id": index + 1,
            "language": code,
            "audio_exclude": "False",
            "hi": "False",
            "forced": "False",
            "audio_only_include": "False",
        }
        for index, code in enumerate(languages)
    ]


def sync_languages(db_path: Path, languages: list[str], profiles: list[dict[str, Any]]) -> bool:
    if not db_path.is_file():
        log("language database not found — skipping language sync")
        return False

    changed = False
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE table_settings_languages SET enabled = 0")
        for code in languages:
            conn.execute(
                "UPDATE table_settings_languages SET enabled = 1 WHERE code2 = ?",
                (code,),
            )
        log(f"enabled languages: {', '.join(languages)}")
        changed = True

        existing = {
            row[0]: row
            for row in conn.execute(
                "SELECT profileId, name, tag, items FROM table_languages_profiles"
            ).fetchall()
        }

        for index, profile in enumerate(profiles, start=1):
            name = profile["name"]
            tag = profile.get("tag", "")
            langs = profile.get("languages") or profile.get("items") or []
            if langs and isinstance(langs[0], dict):
                items = langs
            else:
                items = profile_items(list(langs))
            items_json = json.dumps(items)
            row = existing.get(index)
            if row and row[1] == name and row[2] == tag and row[3] == items_json:
                continue
            if row:
                conn.execute(
                    """
                    UPDATE table_languages_profiles
                    SET name = ?, tag = ?, items = ?, mustContain = '[]', mustNotContain = '[]'
                    WHERE profileId = ?
                    """,
                    (name, tag, items_json, index),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO table_languages_profiles
                    (profileId, name, tag, items, mustContain, mustNotContain, cutoff, originalFormat)
                    VALUES (?, ?, ?, ?, '[]', '[]', NULL, 0)
                    """,
                    (index, name, tag, items_json),
                )
            changed = True
            log(f"updated language profile: {name}")

        conn.commit()
    finally:
        conn.close()

    return changed


def apply_defaults(config: dict[str, Any], defaults: dict[str, Any], profiles: list[dict[str, Any]]) -> bool:
    if not defaults:
        return False

    general = config.setdefault("general", {})
    changed = False
    name_to_id = {profile["name"]: index for index, profile in enumerate(profiles, start=1)}

    for key in ("series_profile", "movie_profile"):
        profile_name = defaults.get(key)
        if not profile_name:
            continue
        profile_id = name_to_id.get(profile_name)
        if profile_id is None:
            raise RuntimeError(f"default profile '{profile_name}' not found in language_profiles")

        config_key = "serie_default_profile" if key == "series_profile" else "movie_default_profile"
        enabled_key = "serie_default_enabled" if key == "series_profile" else "movie_default_enabled"
        if general.get(config_key) != profile_id:
            general[config_key] = profile_id
            changed = True
        if general.get(enabled_key) is not True:
            general[enabled_key] = True
            changed = True

    if changed:
        log("updated default subtitle profiles")
    return changed


def main() -> int:
    base = os.environ.get("BAZARR_URL", "http://127.0.0.1:6767").rstrip("/")
    config_path = Path(
        os.environ.get("BAZARR_CONFIG_YAML", "services/bazarr/config/config/config.yaml")
    )
    db_path = Path(os.environ.get("BAZARR_DB", "services/bazarr/config/db/bazarr.db"))
    sonarr_config = Path(
        os.environ.get("SONARR_CONFIG_XML", "services/sonarr/config/config.xml")
    )
    radarr_config = Path(
        os.environ.get("RADARR_CONFIG_XML", "services/radarr/config/config.xml")
    )

    settings = load_json_env("BAZARR_SETTINGS", {})
    sonarr_port = int(os.environ.get("SONARR_PORT", "8989"))
    radarr_port = int(os.environ.get("RADARR_PORT", "7878"))

    config = load_yaml(config_path)
    bazarr_api_key = config.get("auth", {}).get("apikey") or ""
    if not bazarr_api_key:
        raise RuntimeError(f"No auth.apikey in {config_path}")

    wait_for_api(base, bazarr_api_key)

    changed = False
    changed |= apply_auth(config, settings.get("auth", "none"))

    sonarr_cfg = settings.get("sonarr", {})
    if sonarr_cfg.get("enabled", True):
        changed |= apply_arr_connection(
            config, "sonarr", True, read_api_key(sonarr_config), sonarr_port
        )
    else:
        changed |= apply_arr_connection(config, "sonarr", False, "", sonarr_port)

    radarr_cfg = settings.get("radarr", {})
    if radarr_cfg.get("enabled", True):
        changed |= apply_arr_connection(
            config, "radarr", True, read_api_key(radarr_config), radarr_port
        )
    else:
        changed |= apply_arr_connection(config, "radarr", False, "", radarr_port)

    changed |= apply_providers(config, settings.get("providers", {}))

    profiles = settings.get("language_profiles") or []
    changed |= apply_defaults(config, settings.get("defaults", {}), profiles)

    if changed:
        save_yaml(config_path, config)

    changed |= sync_languages(db_path, settings.get("languages") or ["en"], profiles)

    if not changed:
        log("nothing to change")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
