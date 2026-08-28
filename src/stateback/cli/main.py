"""Top-level Stateback command dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from stateback import __version__
from stateback.cli.config import ProjectConfigError
from stateback.cli.dev import DevError, run_dev
from stateback.cli.init import initialize
from stateback.cli.project import ProjectFileError
from stateback.deployment.processes import PROCESS_NAMES, run_process


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stateback")
    parser.add_argument(
        "--version", action="version", version=f"Stateback {__version__}"
    )
    commands = parser.add_subparsers(dest="command")

    init = commands.add_parser("init", help="initialize Stateback in this project")
    init.add_argument(
        "--json", action="store_true", help="emit machine-readable output"
    )

    dev = commands.add_parser("dev", help="run the local Stateback stack")
    dev.add_argument("--json", action="store_true", help="emit machine-readable status")
    dev.add_argument(
        "--no-browser", action="store_true", help="do not open the Operator UI"
    )

    descriptions = {
        "api": "run the API process (advanced)",
        "relay": "run the outbox relay (advanced)",
        "worker": "run the worker process (advanced)",
        "health": "check worker health (advanced)",
        "nats-init": "initialize JetStream (advanced)",
        "db-privileges": "configure database privileges (advanced)",
        "quarantine-inspect": "inspect quarantined work (advanced)",
        "quarantine-replay": "replay quarantined work (advanced)",
        "quarantine-discard": "discard quarantined work (advanced)",
    }
    for process in PROCESS_NAMES:
        commands.add_parser(process, help=descriptions[process])
    return parser


def _print_init(result_json: bool) -> None:
    result = initialize(Path.cwd())
    if result_json:
        print(json.dumps(result.to_wire(), sort_keys=True, separators=(",", ":")))
        return
    created_labels = {
        "stateback.toml": "Created stateback.toml",
        "stateback.policy.json": "Created stateback.policy.json",
        ".stateback/auth.json": "Created local Stateback credentials",
    }
    existing_labels = {
        "stateback.toml": "stateback.toml already exists",
        "stateback.policy.json": "stateback.policy.json already exists",
        ".stateback/auth.json": "local credentials already exist",
    }
    for path in result.created:
        if path in created_labels:
            print(f"✓ {created_labels[path]}")
    for path in result.existing:
        if path in existing_labels:
            print(f"✓ {existing_labels[path]}")
    print()
    if result.created:
        print("Stateback initialized.")
        print("\nNext:\n  stateback dev")
    else:
        print("Stateback is already initialized.")


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return
    try:
        if args.command == "init":
            _print_init(args.json)
            return
        if args.command == "dev":
            asyncio.run(
                run_dev(json_output=args.json, open_browser=not args.no_browser)
            )
            return
        run_process(args.command)
    except (DevError, ProjectConfigError, ProjectFileError, RuntimeError) as exc:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {"status": "error", "error": str(exc)},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                file=sys.stderr,
            )
        else:
            print(f"Stateback: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
