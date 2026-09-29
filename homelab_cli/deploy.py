"""Ansible deploy dispatch."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from homelab_cli.compose import compose_diff, render_compose, render_compose_content
from homelab_cli.paths import ansible_dir, compose_output, repo_root
from homelab_cli.registry import resolve_deploy_playbooks


def _preview_compose(root: Path) -> None:
    out_path = compose_output(root)
    old_content = out_path.read_text(encoding="utf-8") if out_path.is_file() else ""
    new_content = render_compose_content()
    print("=== compose.yaml ===", flush=True)
    print(
        compose_diff(old_content, new_content, path=str(out_path.relative_to(root))),
        end="",
        flush=True,
    )


def _ansible_env(check_mode: bool, verbose: bool) -> dict[str, str]:
    env: dict[str, str] = {}
    if verbose:
        env["ANSIBLE_DISPLAY_SKIPPED_HOSTS"] = "true"
        env["ANSIBLE_STDOUT_CALLBACK"] = "default"
    else:
        env["ANSIBLE_DISPLAY_SKIPPED_HOSTS"] = "false"
        env["ANSIBLE_STDOUT_CALLBACK"] = "ansible.posix.debug"
    if check_mode:
        env["ANSIBLE_CHECK_MODE_MARKERS"] = "true"
    return env


def run_deploy(
    services: list[str] | None = None,
    deploy_all: bool = False,
    root: Path | None = None,
    check_mode: bool = False,
    diff_mode: bool = False,
    verbose: bool = False,
) -> None:
    root = root or repo_root()
    playbooks = resolve_deploy_playbooks(names=services, deploy_all=deploy_all)
    if not playbooks:
        raise SystemError("No deploy playbooks matched — check config/services.yaml")

    if diff_mode:
        _preview_compose(root)
        print(flush=True)

    if check_mode:
        print(
            "Check mode: compose.yaml not rewritten; Ansible will dry-run playbook tasks.\n",
            flush=True,
        )
    else:
        render_compose()

    ansible = ansible_dir(root)
    env = {"HOMELAB_DIR": str(root), **_ansible_env(check_mode, verbose)}

    for pb in playbooks:
        cmd = ["ansible-playbook", f"playbooks/{pb}"]
        flags: list[str] = []
        if check_mode:
            cmd.append("--check")
            flags.append("--check")
        if diff_mode:
            cmd.append("--diff")
            flags.append("--diff")
        if verbose:
            flags.append("-v")
            cmd.append("-v")
        flag_str = f" {' '.join(flags)}" if flags else ""
        print(f"→ ansible-playbook playbooks/{pb}{flag_str}", flush=True)
        subprocess.run(cmd, cwd=ansible, env={**os.environ, **env}, check=True)
