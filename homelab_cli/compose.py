"""Render compose.tpl.yaml + homelab.yaml → compose.yaml."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from homelab_cli.config import flatten_config, load_config, resolve_data_dir
from homelab_cli.paths import compose_output, compose_template, repo_root

BLOCK_PATTERN = re.compile(r"^\s*\{\{BLOCK:([a-z_]+)\}\}\s*$")
SCALAR_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")


def _render_service_volumes(cfg: dict[str, Any], service: str) -> str:
    volumes = cfg.get(service, {}).get("volumes", [])
    lines = []
    for vol in volumes:
        host = vol.get("host", "")
        container = vol.get("container", "")
        if not host or not container:
            continue
        mount = f"{host}:{container}"
        if vol.get("read_only") or vol.get("ro"):
            mount += ":ro"
        lines.append(f"      - {mount}")
    return "\n".join(lines)


def _service_volumes_block(service: str) -> Callable[[dict[str, Any], dict[str, str]], str]:
    def renderer(cfg: dict[str, Any], _flat: dict[str, str]) -> str:
        return _render_service_volumes(cfg, service)

    return renderer


def _gluetun_api_key(_cfg: dict[str, Any], flat: dict[str, str]) -> str:
    key = flat.get("GLUETUN_API_KEY", "")
    if key:
        return key
    root = repo_root()
    data_dir = resolve_data_dir(_cfg)
    key_file = data_dir / "services" / "gluetun" / "control_api_key"
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


_VOLUME_SERVICES = (
    "audiobookshelf",
    "radarr",
    "sonarr",
    "bazarr",
    "jellyfin",
    "jellyscope",
    "qbittorrent",
)

BLOCK_RENDERERS: dict[str, Callable[[dict[str, Any], dict[str, str]], str]] = {
    **{f"{name}_volumes": _service_volumes_block(name) for name in _VOLUME_SERVICES},
    "gluetun_api_key": _gluetun_api_key,
}


def _apply_kuma_defaults(flat: dict[str, str]) -> None:
    sonarr = flat.get("SONARR_PORT", "8989")
    radarr = flat.get("RADARR_PORT", "7878")
    prowlarr = flat.get("PROWLARR_PORT", "9696")
    bazarr = flat.get("BAZARR_PORT", "6767")
    if not flat.get("KUMA_SONARR_URL"):
        flat["KUMA_SONARR_URL"] = f"http://gluetun:{sonarr}"
    if not flat.get("KUMA_RADARR_URL"):
        flat["KUMA_RADARR_URL"] = f"http://gluetun:{radarr}"
    if not flat.get("KUMA_PROWLARR_URL"):
        flat["KUMA_PROWLARR_URL"] = f"http://gluetun:{prowlarr}"
    if not flat.get("KUMA_BAZARR_URL"):
        flat["KUMA_BAZARR_URL"] = f"http://gluetun:{bazarr}"
    if not flat.get("KUMA_DISPATCHARR_URL"):
        flat["KUMA_DISPATCHARR_URL"] = "http://dispatcharr:9191"


def _resolve_scalar(token: str, cfg: dict[str, Any], flat: dict[str, str]) -> str:
    if re.match(r"^[A-Z][A-Z0-9_]*$", token):
        return flat.get(token, "")
    from homelab_cli.config import lookup

    value = lookup(cfg, token)
    if value is None:
        return ""
    return str(value)


def render_compose_content(
    tpl_path: Path | None = None,
    cfg_path: Path | None = None,
) -> str:
    cfg = load_config(cfg_path)
    flat = flatten_config(cfg)
    _apply_kuma_defaults(flat)
    if not flat.get("GLUETUN_API_KEY"):
        flat["GLUETUN_API_KEY"] = _gluetun_api_key(cfg, flat)

    template = (tpl_path or compose_template()).read_text(encoding="utf-8")
    output_lines: list[str] = []

    for line in template.splitlines():
        block_match = BLOCK_PATTERN.match(line)
        if block_match:
            name = block_match.group(1)
            renderer = BLOCK_RENDERERS.get(name)
            if not renderer:
                raise ValueError(f"Unknown compose block: {name}")
            rendered = renderer(cfg, flat)
            if rendered:
                output_lines.append(rendered)
            continue

        def repl(match: re.Match[str]) -> str:
            return _resolve_scalar(match.group(1), cfg, flat)

        output_lines.append(SCALAR_PATTERN.sub(repl, line))

    return "\n".join(output_lines) + "\n"


def compose_diff(
    old_content: str,
    new_content: str,
    path: str = "compose.yaml",
) -> str:
    import difflib

    if old_content == new_content:
        return f"{path}: unchanged\n"

    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


def render_compose(
    tpl_path: Path | None = None,
    out_path: Path | None = None,
    cfg_path: Path | None = None,
) -> Path:
    out = out_path or compose_output()
    content = render_compose_content(tpl_path=tpl_path, cfg_path=cfg_path)
    out.write_text(content, encoding="utf-8")
    out.chmod(0o600)
    return out
