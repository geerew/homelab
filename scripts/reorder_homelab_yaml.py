#!/usr/bin/env python3
"""Reorder top-level keys in homelab.yaml / homelab.example.yaml with section headers."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SECTIONS: list[tuple[str, list[str]]] = [
    ("# --- Core ---", ["core"]),
    ("# --- Infrastructure ---", ["socket_proxy", "watchtower", "dozzle", "cloudflare"]),
    ("# --- Authentication ---", ["authelia"]),
    ("# --- Monitoring & dashboard ---", ["uptime_kuma", "homepage"]),
    ("# --- Shared media paths ---", ["media"]),
    ("# --- VPN & *arr stack ---", ["gluetun", "qbittorrent", "prowlarr", "radarr"]),
    ("# --- IPTV ---", ["dispatcharr"]),
    ("# --- Apps ---", ["audiobookshelf", "mealie", "jellyscope", "memos"]),
    ("# --- Other ---", ["mcclean", "sparkyfitness"]),
]

BLOCK_SCALAR_KEYS = frozenset({"jwks_private_key"})


def reorder(data: dict) -> dict:
    out: dict = {}
    seen: set[str] = set()
    for _label, keys in SECTIONS:
        for key in keys:
            if key in data:
                out[key] = data[key]
                seen.add(key)
    for key, value in data.items():
        if key not in seen:
            out[key] = value
    return out


def yaml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "''"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return "''"
    if any(ch in text for ch in ":{}[]&*#?|-<>=!%@`\"'"):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def dump_block_scalar(key: str, value: str, indent: int) -> list[str]:
    prefix = " " * indent
    lines = [f"{prefix}{key}: |"]
    for line in value.rstrip("\n").splitlines():
        lines.append(f"{prefix}  {line}")
    return lines


def dump_value(key: str, value: object, indent: int) -> list[str]:
    prefix = " " * indent
    if key in BLOCK_SCALAR_KEYS and isinstance(value, str):
        return dump_block_scalar(key, value, indent)
    if isinstance(value, dict):
        lines = [f"{prefix}{key}:"]
        for sub_key, sub_val in value.items():
            lines.extend(dump_value(sub_key, sub_val, indent + 2))
        return lines
    if isinstance(value, list):
        lines = [f"{prefix}{key}:"]
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}  -")
                for sub_key, sub_val in item.items():
                    if isinstance(sub_val, (dict, list)):
                        lines.extend(dump_value(sub_key, sub_val, indent + 4))
                    else:
                        lines.append(f"{prefix}    {sub_key}: {yaml_scalar(sub_val)}")
            else:
                lines.append(f"{prefix}  - {yaml_scalar(item)}")
        return lines
    return [f"{prefix}{key}: {yaml_scalar(value)}"]


def write_config(path: Path, data: dict, include_comments: bool) -> None:
    section_map = {k: label for label, keys in SECTIONS for k in keys}
    lines: list[str] = []
    prev_label: str | None = None
    for key, value in data.items():
        label = section_map.get(key)
        if label and label != prev_label:
            if lines:
                lines.append("")
            if include_comments:
                lines.append(label)
            prev_label = label
        lines.extend(dump_value(key, value, 0))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    root = Path(__file__).resolve().parents[1]
    targets = argv[1:] or ["homelab.example.yaml", "homelab.yaml"]
    for name in targets:
        path = root / name
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        include_comments = name.endswith(".example.yaml") or name == "backups/homelab.yaml"
        write_config(path, reorder(data), include_comments=include_comments)
        print(f"reordered {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
