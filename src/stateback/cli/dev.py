"""Deterministic orchestration of the existing Stateback runtime processes."""

from __future__ import annotations

import asyncio
import errno
import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import urllib.error
import urllib.request
import webbrowser
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import Protocol, TextIO

from stateback import __version__
from stateback.cli.config import ProjectConfig, load_project_config
from stateback.cli.docker import (
    DockerRunner,
    LocalDockerRunner,
    PortChecker,
    SocketPortChecker,
    compose_environment,
)
from stateback.cli.project import find_project_root
from stateback.cli.supervisor import (
    Child,
    ProcessSupervisor,
    SupervisorError,
    run_one_shot,
)
from stateback.persistence.migrate import upgrade_head


class DevError(RuntimeError):
    """The local composition cannot start or remain healthy."""


class RuntimeSupervisor(Protocol):
    async def migrate(self, database_url: str) -> None: ...

    async def provision(self, environment: Mapping[str, str]) -> None: ...

    async def start_api(
        self, environment: Mapping[str, str], ready_url: str
    ) -> None: ...

    async def start_relay(
        self, environment: Mapping[str, str], marker: Path
    ) -> None: ...

    async def start_worker(
        self, environment: Mapping[str, str], marker: Path
    ) -> None: ...

    async def supervise(self, stop: asyncio.Event) -> None: ...

    async def shutdown(self) -> None: ...


class LocalRuntimeSupervisor:
    def __init__(self, log_directory: Path, *, show_output: bool) -> None:
        self._supervisor = ProcessSupervisor(log_directory, show_output=show_output)

    async def migrate(self, database_url: str) -> None:
        await asyncio.to_thread(upgrade_head, database_url)

    async def provision(self, environment: Mapping[str, str]) -> None:
        await run_one_shot("nats-init", environment)

    async def start_api(self, environment: Mapping[str, str], ready_url: str) -> None:
        api = await self._supervisor.start("api", environment)
        await _wait_for_api(api, ready_url)

    async def start_relay(self, environment: Mapping[str, str], marker: Path) -> None:
        relay = await self._supervisor.start("relay", environment)
        await self._supervisor.wait_for_marker(relay, marker)

    async def start_worker(self, environment: Mapping[str, str], marker: Path) -> None:
        worker = await self._supervisor.start("worker", environment)
        await self._supervisor.wait_for_marker(worker, marker)

    async def supervise(self, stop: asyncio.Event) -> None:
        await self._supervisor.wait_for_exit_or_stop(stop)

    async def shutdown(self) -> None:
        await self._supervisor.shutdown()


class DevLock:
    def __init__(self, path: Path, project_root: Path) -> None:
        self._path = path
        self._project_root = project_root
        self._stream: TextIO | None = None

    def __enter__(self) -> DevLock:
        stream = self._path.open("a+", encoding="ascii")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise DevError(
                    "Stateback dev is already running for this project.\n\n"
                    f"Project:\n  {self._project_root}"
                ) from None
            raise
        stream.seek(0)
        stream.truncate()
        stream.write(f"{os.getpid()}\n")
        stream.flush()
        self._stream = stream
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        assert self._stream is not None
        stream = self._stream
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _compose_project(config: ProjectConfig) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", config.name.lower()).strip("-")
    digest = hashlib.sha256(str(config.root).encode()).hexdigest()[:8]
    return f"stateback-{slug[:30] or 'project'}-{digest}"


def _runtime_environment(config: ProjectConfig) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("STATEBACK_")
    }
    database_url = (
        "postgresql+psycopg://stateback:stateback_dev_only@"
        f"{config.dev.postgres_host}:{config.dev.postgres_port}/stateback"
    )
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "STATEBACK_DATABASE_URL": database_url,
            "STATEBACK_NATS_URL": f"nats://{config.dev.nats_host}:{config.dev.nats_port}",
            "STATEBACK_NATS_BOOTSTRAP_URL": (
                f"nats://{config.dev.nats_host}:{config.dev.nats_port}"
            ),
            "STATEBACK_POLICY_CONFIG_FILE": str(config.paths.policy),
            "STATEBACK_AUTH_CONFIG_FILE": str(config.paths.auth),
            "STATEBACK_GITHUB_CONFIGURED": "1" if config.github_enabled else "0",
            "STATEBACK_API_HOST": config.dev.api_host,
            "STATEBACK_API_PORT": str(config.dev.api_port),
            "STATEBACK_SERVE_OPERATOR_UI": "1",
        }
    )
    return environment


def _require_project_files(config: ProjectConfig) -> None:
    state_directory = config.root / ".stateback"
    if state_directory.is_symlink() or not state_directory.is_dir():
        raise DevError(
            f"Stateback local state directory is missing or unsafe: {state_directory}"
        )
    for label, path in (
        ("policy", config.paths.policy),
        ("authentication", config.paths.auth),
    ):
        if path.is_symlink() or not path.is_file():
            raise DevError(
                f"Stateback {label} configuration is missing or unsafe: {path}"
            )
    if os.name == "posix" and stat.S_IMODE(config.paths.auth.stat().st_mode) & 0o077:
        raise DevError(
            "Stateback authentication configuration must not be group/world accessible"
        )
    if config.github_enabled and (
        config.paths.github_token.is_symlink()
        or not config.paths.github_token.is_file()
    ):
        raise DevError(
            "GitHub is enabled, but its token file is missing or unsafe: "
            f"{config.paths.github_token}"
        )
    if (
        config.github_enabled
        and os.name == "posix"
        and stat.S_IMODE(config.paths.github_token.stat().st_mode) & 0o077
    ):
        raise DevError("the GitHub token file must have mode 0600")


async def _wait_for_api(child: Child, url: str, timeout: float = 30) -> None:
    deadline = asyncio.get_running_loop().time() + timeout

    def ready() -> bool:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:  # noqa: S310
                return bool(response.status == 200)
        except (OSError, urllib.error.URLError):
            return False

    while asyncio.get_running_loop().time() < deadline:
        if child.process.returncode is not None:
            await child.output_task
            details = "\n".join(f"  {line}" for line in child.last_lines)
            raise SupervisorError(
                "Stateback API exited before readiness"
                + (f"\n\nLast log lines:\n{details}" if details else "")
            )
        if await asyncio.to_thread(ready):
            return
        await asyncio.sleep(0.2)
    raise SupervisorError("Stateback API did not become ready")


def _install_signal_handlers(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass


async def run_dev(
    *,
    json_output: bool,
    open_browser: bool,
    docker: DockerRunner | None = None,
    ports: PortChecker | None = None,
    runtime: RuntimeSupervisor | None = None,
) -> None:
    root = find_project_root(Path.cwd())
    config = load_project_config(root / "stateback.toml")
    _require_project_files(config)
    docker_runner = docker or LocalDockerRunner()
    port_checker = ports or SocketPortChecker()
    run_directory = root / ".stateback" / "run"
    log_directory = root / ".stateback" / "logs"
    if not run_directory.is_dir() or not log_directory.is_dir():
        raise DevError("local runtime directories are missing; run `stateback init`")

    compose_file = Path(str(files("stateback.cli.assets").joinpath("compose.dev.yaml")))
    compose_project = _compose_project(config)
    compose_env = compose_environment(
        postgres_port=config.dev.postgres_port,
        nats_port=config.dev.nats_port,
        monitor_port=config.dev.nats_monitor_port,
    )
    runtime_env = _runtime_environment(config)
    database_url = runtime_env["STATEBACK_DATABASE_URL"]
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    with DevLock(run_directory / "dev.lock", root):
        if not json_output:
            print(f"Stateback {__version__}\n", flush=True)
        await docker_runner.preflight()
        if not json_output:
            print("✓ Docker")
        for host, port, service in (
            (config.dev.postgres_host, config.dev.postgres_port, "PostgreSQL"),
            (config.dev.nats_host, config.dev.nats_port, "NATS JetStream"),
            (config.dev.nats_host, config.dev.nats_monitor_port, "NATS monitoring"),
            (config.dev.api_host, config.dev.api_port, "API"),
        ):
            port_checker.require_available(host, port, service)

        runtime_supervisor = runtime or LocalRuntimeSupervisor(
            log_directory, show_output=not json_output
        )
        compose_attempted = False
        try:
            compose_attempted = True
            await docker_runner.compose_up(
                project=compose_project,
                compose_file=compose_file,
                environment=compose_env,
            )
            if not json_output:
                print(
                    f"✓ PostgreSQL        {config.dev.postgres_host}:{config.dev.postgres_port}"
                )
                print(
                    f"✓ NATS JetStream    {config.dev.nats_host}:{config.dev.nats_port}"
                )

            await runtime_supervisor.migrate(database_url)
            if not json_output:
                print("✓ Database schema   up to date")
            await runtime_supervisor.provision(runtime_env)
            if not json_output:
                print("✓ JetStream         initialized")

            api_url = f"http://{config.dev.api_host}:{config.dev.api_port}"
            await runtime_supervisor.start_api(runtime_env, f"{api_url}/health/ready")
            if not json_output:
                print(f"✓ API               {api_url}")

            relay_env = dict(runtime_env)
            relay_marker = run_directory / "relay.ready"
            relay_env["STATEBACK_READINESS_PATH"] = str(relay_marker)
            await runtime_supervisor.start_relay(relay_env, relay_marker)
            if not json_output:
                print("✓ Relay             ready")

            worker_env = dict(runtime_env)
            worker_marker = run_directory / "worker.ready"
            worker_env["STATEBACK_READINESS_PATH"] = str(worker_marker)
            if config.github_enabled:
                worker_env["STATEBACK_GITHUB_TOKEN_FILE"] = str(
                    config.paths.github_token
                )
            await runtime_supervisor.start_worker(worker_env, worker_marker)
            if not json_output:
                print("✓ Worker            ready")
                print(f"✓ Operator UI       {api_url}")
                print("\nStateback is ready.\n\nPress Ctrl+C to stop.")
            else:
                print(
                    json.dumps(
                        {
                            "status": "ready",
                            "project_root": str(root),
                            "api_url": api_url,
                            "operator_ui_url": api_url,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            if open_browser:
                await asyncio.to_thread(webbrowser.open, api_url)
            await runtime_supervisor.supervise(stop)
        except SupervisorError as exc:
            raise DevError(str(exc)) from exc
        finally:
            await runtime_supervisor.shutdown()
            if compose_attempted:
                await docker_runner.compose_down(
                    project=compose_project,
                    compose_file=compose_file,
                    environment=compose_env,
                )
