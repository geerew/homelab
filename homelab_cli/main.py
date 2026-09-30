"""Homelab CLI entrypoint."""

from __future__ import annotations

import argparse
import subprocess
import sys

from homelab_cli import __version__
from homelab_cli.compose import render_compose
from homelab_cli.config import ConfigError, load_config, validate_config
from homelab_cli import backup as backup_mod
from homelab_cli import deploy as deploy_mod
from homelab_cli import docker as docker_mod
from homelab_cli.registry import backupable_services, load_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="homelab", description="Homelab stack manager")
    parser.add_argument("--version", action="version", version=f"homelab {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    config_p = sub.add_parser("config", help="Configuration commands")
    config_sub = config_p.add_subparsers(dest="config_cmd", required=True)
    config_sub.add_parser("validate", help="Validate homelab.yaml")

    compose_p = sub.add_parser("compose", help="Compose file commands")
    compose_sub = compose_p.add_subparsers(dest="compose_cmd", required=True)
    compose_sub.add_parser("generate", help="Render compose.yaml from compose.tpl.yaml")

    up_p = sub.add_parser("up", help="Generate compose and docker compose up -d")
    up_p.add_argument("services", nargs="*", metavar="SERVICE")
    for name, help_text in (
        ("down", "Stop services or full stack down"),
        ("start", "Start services"),
        ("stop", "Stop services"),
        ("restart", "Restart services"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("services", nargs="*", metavar="SERVICE")

    deploy_p = sub.add_parser("deploy", help="Run Ansible deploy playbooks")
    deploy_p.add_argument("services", nargs="*", metavar="SERVICE")
    deploy_p.add_argument("--all", action="store_true", help="Run full deploy-services order")
    deploy_p.add_argument(
        "--check",
        action="store_true",
        help="Dry-run: preview changes without applying (Ansible --check)",
    )
    deploy_p.add_argument(
        "--diff",
        action="store_true",
        help="Show diffs for compose.yaml and Ansible-managed files (use with --check to preview)",
    )
    deploy_p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Full Ansible output (show skipped tasks, default callback)",
    )

    backup_p = sub.add_parser("backup", help="Back up service data under services/<name>/")
    backup_p.add_argument("services", nargs="*", metavar="SERVICE")
    backup_p.add_argument(
        "--all",
        action="store_true",
        help="Back up every service marked backup: true in config/services.yaml",
    )
    backup_p.add_argument(
        "--label",
        metavar="NAME",
        help="Prefix backup folder (e.g. manual → manual-20260929T191045Z)",
    )
    backup_p.add_argument(
        "--list",
        action="store_true",
        help="List services included in backup --all",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "config":
            if args.config_cmd == "validate":
                cfg = load_config()
                errors = validate_config(cfg)
                if errors:
                    for err in errors:
                        print(f"ERROR: {err}", file=sys.stderr)
                    return 1
                print("homelab.yaml OK")
                return 0

        if args.command == "compose":
            if args.compose_cmd == "generate":
                out = render_compose()
                print(f"Wrote {out}")
                return 0

        if args.command == "up":
            docker_mod.up(args.services or None)
            return 0

        if args.command == "down":
            docker_mod.down(args.services or None)
            return 0

        if args.command == "start":
            docker_mod.start(args.services or None)
            return 0

        if args.command == "stop":
            docker_mod.stop(args.services or None)
            return 0

        if args.command == "restart":
            docker_mod.restart(args.services or None)
            return 0

        if args.command == "deploy":
            if not args.all and not args.services:
                print("Specify service names or --all", file=sys.stderr)
                return 1
            deploy_mod.run_deploy(
                services=args.services or None,
                deploy_all=args.all,
                check_mode=args.check,
                diff_mode=args.diff,
                verbose=args.verbose,
            )
            return 0

        if args.command == "backup":
            if args.list:
                names = backupable_services(load_registry())
                if names:
                    print("Services in backup --all:")
                    for name in names:
                        print(f"  {name}")
                else:
                    print("No services marked backup: true in config/services.yaml")
                return 0
            if not args.all and not args.services:
                print("Specify service names, --all, or --list", file=sys.stderr)
                return 1
            backup_mod.run_backup(
                services=args.services or None,
                backup_all=args.all,
                label=args.label,
            )
            return 0

    except ConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except backup_mod.BackupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode or 1

    parser.print_help()
    return 1
