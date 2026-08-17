#!/usr/bin/env python3
"""Versioned correctness and public-boundary performance runner."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import cast

from benchmarks.catalog import SCENARIOS

BENCHMARK_VERSION = "sb-bench-v1"
DEFAULT_SEED = 1709
DEFAULT_WARMUPS = 5
DEFAULT_REPETITIONS = 30


def _git_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_tree_sha256() -> str:
    files: set[Path] = set()
    for root in (Path("src"), Path("tests"), Path("benchmarks"), Path("frontend/src")):
        files.update(path for path in root.rglob("*") if path.is_file())
    files.update(
        path
        for path in (
            Path("pyproject.toml"),
            Path("uv.lock"),
            Path("frontend/package.json"),
            Path("frontend/package-lock.json"),
            Path("contracts/BENCHMARK_CONTRACT.md"),
            Path("contracts/PUBLIC_API_CONTRACT.md"),
            Path("contracts/OPERATOR_CONTRACT.md"),
            Path("tasks/SB-009.md"),
        )
        if path.is_file()
    )
    digest = hashlib.sha256()
    for path in sorted(files):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _environment() -> dict[str, object]:
    dependencies: dict[str, str] = {}
    for name in ("stateback", "fastapi", "httpx", "mcp", "sqlalchemy"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "not-installed"
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "dependency_versions": dependencies,
    }


def _provenance_environment() -> tuple[dict[str, object], str, dict[str, str]]:
    environment = _environment()
    return (
        environment,
        str(environment["python_version"]),
        dict(cast(dict[str, str], environment["dependency_versions"])),
    )


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def correctness(output: Path) -> int:
    if os.environ.get("STATEBACK_RUN_INTEGRATION") != "1":
        raise SystemExit(
            "correctness evidence requires STATEBACK_RUN_INTEGRATION=1; "
            "skipped infrastructure scenarios are not a pass"
        )
    postgres_version = os.environ.get("STATEBACK_BENCH_POSTGRES_VERSION")
    nats_version = os.environ.get("STATEBACK_BENCH_NATS_VERSION")
    if not postgres_version or not nats_version:
        raise SystemExit(
            "correctness evidence requires STATEBACK_BENCH_POSTGRES_VERSION and "
            "STATEBACK_BENCH_NATS_VERSION"
        )
    python_nodes = [
        item.node_id for item in SCENARIOS if item.node_id.startswith("tests/")
    ]
    commands = [
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-m",
            "benchmark_correctness",
            *python_nodes,
        ],
        ["npm", "test", "--", "--run", "src/App.test.tsx"],
    ]
    results: list[dict[str, object]] = []
    exit_code = 0
    for command in commands:
        cwd = Path("frontend") if command[0] == "npm" else Path(".")
        started = time.monotonic_ns()
        completed = subprocess.run(command, cwd=cwd, check=False)
        elapsed = time.monotonic_ns() - started
        results.append(
            {
                "command": command,
                "exit_code": completed.returncode,
                "elapsed_ns": elapsed,
            }
        )
        exit_code = max(exit_code, completed.returncode)
    environment, python_version, dependency_versions = _provenance_environment()
    raw_measurements = [cast(int, result["elapsed_ns"]) for result in results]
    _write(
        output,
        {
            "benchmark_version": BENCHMARK_VERSION,
            "stateback_commit_sha": _git_sha(),
            "source_tree_sha256": _source_tree_sha256(),
            "kind": "correctness",
            "workload": "cataloged deterministic correctness scenarios",
            "configuration": {
                "integration_enabled": os.environ.get("STATEBACK_RUN_INTEGRATION")
                == "1"
            },
            "seed": DEFAULT_SEED,
            "warmups": 0,
            "repetitions": 1,
            "aggregation": "none; every command result retained",
            "environment": environment,
            "python_version": python_version,
            "dependency_versions": dependency_versions,
            "postgres_version": postgres_version,
            "nats_version": nats_version,
            "raw_measurements_ns": raw_measurements,
            "scenarios": [asdict(item) for item in SCENARIOS],
            "results": results,
            "failures": [result for result in results if result["exit_code"] != 0],
            "exclusions": [],
            "summary": {
                "commands": len(results),
                "passed": sum(result["exit_code"] == 0 for result in results),
            },
        },
    )
    return exit_code


def _measure(action: Callable[[], object], warmups: int, repetitions: int) -> list[int]:
    for _ in range(warmups):
        action()
    samples: list[int] = []
    for _ in range(repetitions):
        started = time.monotonic_ns()
        action()
        samples.append(time.monotonic_ns() - started)
    return samples


def _summary(samples: list[int]) -> dict[str, int]:
    ordered = sorted(samples)
    p95_index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return {
        "median_ns": int(statistics.median(ordered)),
        "p95_ns": ordered[p95_index],
    }


def performance(
    output: Path,
    *,
    api_url: str,
    operation_id: str,
    warmups: int,
    repetitions: int,
    seed: int,
) -> int:
    from stateback.sdk import StatebackClient

    token = os.environ.get("STATEBACK_BENCH_TOKEN")
    if not token:
        raise SystemExit("STATEBACK_BENCH_TOKEN is required and is never recorded")
    random.seed(seed)
    client = StatebackClient(base_url=api_url, token=token)
    failures: list[dict[str, str]] = []
    cases: dict[str, dict[str, object]] = {}
    actions: dict[str, Callable[[], object]] = {
        "api_operation_status": lambda: client.get_operation(operation_id),
        "api_audit_query": lambda: client.get_audit(operation_id, limit=100),
    }
    try:
        for name, action in actions.items():
            try:
                samples = _measure(action, warmups, repetitions)
            except Exception as exc:
                failures.append({"case": name, "error_type": type(exc).__name__})
                continue
            cases[name] = {
                "workload": "authenticated HTTP GET over production public path",
                "raw_measurements_ns": samples,
                "summary": _summary(samples),
            }
    finally:
        client.close()
    environment, python_version, dependency_versions = _provenance_environment()
    raw_measurements = {
        name: case["raw_measurements_ns"] for name, case in cases.items()
    }
    summaries = {name: case["summary"] for name, case in cases.items()}
    _write(
        output,
        {
            "benchmark_version": BENCHMARK_VERSION,
            "stateback_commit_sha": _git_sha(),
            "source_tree_sha256": _source_tree_sha256(),
            "kind": "performance",
            "workload": "public operation status and ordered audit reads",
            "configuration": {"api_url": api_url, "operation_id": operation_id},
            "seed": seed,
            "warmups": warmups,
            "repetitions": repetitions,
            "aggregation": "median and nearest-rank p95",
            "environment": environment,
            "python_version": python_version,
            "dependency_versions": dependency_versions,
            "postgres_version": os.environ.get("STATEBACK_BENCH_POSTGRES_VERSION"),
            "nats_version": os.environ.get("STATEBACK_BENCH_NATS_VERSION"),
            "raw_measurements_ns": raw_measurements,
            "cases": cases,
            "failures": failures,
            "exclusions": [],
            "summary": summaries,
        },
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    correctness_parser = subparsers.add_parser("correctness")
    correctness_parser.add_argument("--output", type=Path, required=True)
    performance_parser = subparsers.add_parser("performance")
    performance_parser.add_argument("--output", type=Path, required=True)
    performance_parser.add_argument("--api-url", required=True)
    performance_parser.add_argument("--operation-id", required=True)
    performance_parser.add_argument("--warmups", type=int, default=DEFAULT_WARMUPS)
    performance_parser.add_argument(
        "--repetitions", type=int, default=DEFAULT_REPETITIONS
    )
    performance_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    if args.command == "correctness":
        return correctness(args.output)
    if args.warmups < 0 or args.repetitions < 1:
        parser.error("warmups must be >= 0 and repetitions must be >= 1")
    return performance(
        args.output,
        api_url=args.api_url,
        operation_id=args.operation_id,
        warmups=args.warmups,
        repetitions=args.repetitions,
        seed=args.seed,
    )


if __name__ == "__main__":
    raise SystemExit(main())
