"""Top-level Stateback command dispatch."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from stateback import __version__
from stateback.cli.config import ProjectConfigError
from stateback.cli.connect import connect_github
from stateback.cli.demo import DemoError, run_unknown_demo
from stateback.cli.dev import DevError, run_dev
from stateback.cli.init import initialize
from stateback.cli.mcp import run_mcp
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

    connect = commands.add_parser("connect", help="connect a provider")
    connect.add_argument("provider", choices=("github",))

    mcp = commands.add_parser("mcp", help="run the Stateback MCP server over stdio")
    mcp.add_argument(
        "--print-config",
        action="store_true",
        help="print a generic stdio config fragment",
    )

    demo = commands.add_parser("demo", help="run an explicit Stateback product demo")
    demo.add_argument("scenario", choices=("unknown",))
    demo.add_argument("--owner", required=True)
    demo.add_argument("--repo", required=True)
    demo.add_argument("--confirm-mutation", action="store_true")

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
    commands.add_parser("_dev-worker", help=argparse.SUPPRESS)
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
    if result.created:
        print("Stateback initialized\n")
    else:
        print("Stateback is already initialized\n")
    for path in result.created:
        if path in created_labels:
            print(f"✓ {created_labels[path]}")
    for path in result.existing:
        if path in existing_labels:
            print(f"✓ {existing_labels[path]}")
    if result.created:
        print("\nNext:\n  stateback dev")


def _connect_github() -> None:
    print("Connecting GitHub...\n")
    connection = connect_github()
    print(f"✓ Authenticated as {connection.account}")
    print("✓ Credential stored securely")
    print("✓ GitHub provider enabled")
    print("\nGitHub is connected.")


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
        if args.command == "connect":
            _connect_github()
            return
        if args.command == "mcp":
            run_mcp(print_config=args.print_config)
            return
        if args.command == "demo":
            run_unknown_demo(
                owner=args.owner,
                repo=args.repo,
                confirm_mutation=args.confirm_mutation,
            )
            return
        if args.command == "_dev-worker":
            from stateback.deployment.processes import run_worker

            asyncio.run(run_worker(development=True))
            return
        run_process(args.command)
    except (
        DevError,
        DemoError,
        ProjectConfigError,
        ProjectFileError,
        RuntimeError,
    ) as exc:
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
