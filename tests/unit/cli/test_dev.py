from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from stateback.cli import dev as dev_module
from stateback.cli import docker as docker_module
from stateback.cli.config import load_project_config
from stateback.cli.dev import DevError, DevLock, _create_dev_auth, run_dev
from stateback.cli.docker import DockerError, LocalDockerRunner, SocketPortChecker
from stateback.cli.init import initialize
from stateback.cli.supervisor import Child, ProcessSupervisor, SupervisorError

pytestmark = pytest.mark.unit


class FakeDocker:
    def __init__(
        self,
        failure: DockerError | None = None,
        up_failure: DockerError | None = None,
    ) -> None:
        self.failure = failure
        self.up_failure = up_failure
        self.events: list[str] = []
        self.api_environment: Mapping[str, str] = {}

    async def preflight(self) -> None:
        self.events.append("preflight")
        if self.failure is not None:
            raise self.failure

    async def compose_up(
        self, *, project: str, compose_file: Path, environment: Mapping[str, str]
    ) -> None:
        assert compose_file.name == "compose.dev.yaml"
        assert project.startswith("stateback-")
        assert environment["STATEBACK_POSTGRES_PORT"] == "5432"
        self.events.append("up")
        if self.up_failure is not None:
            raise self.up_failure

    async def compose_down(
        self, *, project: str, compose_file: Path, environment: Mapping[str, str]
    ) -> None:
        self.events.append("down")


class FreePorts:
    def require_available(self, host: str, port: int, service: str) -> None:
        pass


class FakeRuntime:
    def __init__(self, failure_at: str | None = None) -> None:
        self.failure_at = failure_at
        self.events: list[str] = []
        self.worker_environment: Mapping[str, str] = {}

    def record(self, event: str) -> None:
        self.events.append(event)
        if self.failure_at == event:
            raise SupervisorError(f"{event} failed")

    async def migrate(self, database_url: str) -> None:
        assert "stateback_dev_only" in database_url
        self.record("migrate")

    async def provision(self, environment: Mapping[str, str]) -> None:
        assert environment["STATEBACK_NATS_BOOTSTRAP_URL"].startswith("nats://")
        self.record("provision")

    async def start_api(self, environment: Mapping[str, str], ready_url: str) -> None:
        self.api_environment = environment
        assert environment["STATEBACK_SERVE_OPERATOR_UI"] == "1"
        assert "STATEBACK_GITHUB_TOKEN_FILE" not in environment
        assert ready_url.endswith("/health/ready")
        self.record("api")

    async def start_relay(self, environment: Mapping[str, str], marker: Path) -> None:
        assert environment["STATEBACK_READINESS_PATH"] == str(marker)
        self.record("relay")

    async def start_worker(self, environment: Mapping[str, str], marker: Path) -> None:
        self.worker_environment = environment
        assert environment["STATEBACK_READINESS_PATH"] == str(marker)
        self.record("worker")

    async def supervise(self, stop: asyncio.Event) -> None:
        self.record("supervise")

    async def shutdown(self) -> None:
        self.record("shutdown")


def test_dev_orchestrates_in_dependency_order_and_emits_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STATEBACK_GITHUB_TOKEN_FILE", "/must/not/leak")
    docker = FakeDocker()
    runtime = FakeRuntime()

    asyncio.run(
        run_dev(
            json_output=True,
            open_browser=False,
            docker=docker,
            ports=FreePorts(),
            runtime=runtime,
        )
    )

    assert docker.events == ["preflight", "up", "down"]
    assert runtime.events == [
        "migrate",
        "provision",
        "api",
        "relay",
        "worker",
        "supervise",
        "shutdown",
    ]
    assert "STATEBACK_GITHUB_TOKEN_FILE" not in runtime.worker_environment
    assert runtime.api_environment["STATEBACK_AUTH_CONFIG_FILE"].endswith(
        ".stateback/run/auth.json"
    )
    assert not (tmp_path / ".stateback/run/auth.json").exists()
    assert json.loads(capsys.readouterr().out)["status"] == "ready"


def test_dev_uses_ephemeral_bootstrap_without_changing_permanent_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initialize(tmp_path)
    permanent = tmp_path / ".stateback/auth.json"
    original = permanent.read_bytes()
    opened: list[str] = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("stateback.cli.dev.webbrowser.open", opened.append)

    asyncio.run(
        run_dev(
            json_output=False,
            open_browser=True,
            docker=FakeDocker(),
            ports=FreePorts(),
            runtime=FakeRuntime(),
        )
    )

    assert permanent.read_bytes() == original
    assert len(opened) == 1
    assert opened[0].startswith("http://127.0.0.1:8080/#stateback-bootstrap=")
    token = opened[0].partition("=")[2]
    assert len(token) >= 32
    assert token not in capsys.readouterr().out
    assert not (tmp_path / ".stateback/run/auth.json").exists()


def test_dev_bootstrap_is_disabled_for_non_loopback_hosts(tmp_path: Path) -> None:
    initialize(tmp_path)
    config = load_project_config(tmp_path / "stateback.toml")
    exposed = replace(config, dev=replace(config.dev, api_host="0.0.0.0"))

    assert _create_dev_auth(exposed, tmp_path / ".stateback/run") is None
    assert not (tmp_path / ".stateback/run/auth.json").exists()


def test_github_token_path_is_given_only_to_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    config = tmp_path / "stateback.toml"
    config.write_text(config.read_text().replace("enabled = false", "enabled = true"))
    token = tmp_path / ".stateback/secrets/github-token"
    token.write_text("test-only-token")
    token.chmod(0o600)
    monkeypatch.chdir(tmp_path)
    runtime = FakeRuntime()

    asyncio.run(
        run_dev(
            json_output=True,
            open_browser=False,
            docker=FakeDocker(),
            ports=FreePorts(),
            runtime=runtime,
        )
    )

    assert runtime.worker_environment["STATEBACK_GITHUB_TOKEN_FILE"] == str(token)


def test_dev_reports_docker_preflight_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    failure = DockerError("Docker daemon is not running")

    with pytest.raises(DockerError, match="daemon"):
        asyncio.run(
            run_dev(
                json_output=True,
                open_browser=False,
                docker=FakeDocker(failure),
                ports=FreePorts(),
                runtime=FakeRuntime(),
            )
        )


def test_partial_compose_start_is_torn_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    docker = FakeDocker(up_failure=DockerError("PostgreSQL failed health"))
    runtime = FakeRuntime()

    with pytest.raises(DockerError, match="failed health"):
        asyncio.run(
            run_dev(
                json_output=True,
                open_browser=False,
                docker=docker,
                ports=FreePorts(),
                runtime=runtime,
            )
        )

    assert docker.events == ["preflight", "up", "down"]
    assert runtime.events == ["shutdown"]


@pytest.mark.parametrize(
    ("failure_at", "expected_runtime_events"),
    [
        ("migrate", ["migrate", "shutdown"]),
        ("provision", ["migrate", "provision", "shutdown"]),
        ("api", ["migrate", "provision", "api", "shutdown"]),
        ("relay", ["migrate", "provision", "api", "relay", "shutdown"]),
        (
            "worker",
            ["migrate", "provision", "api", "relay", "worker", "shutdown"],
        ),
        (
            "supervise",
            [
                "migrate",
                "provision",
                "api",
                "relay",
                "worker",
                "supervise",
                "shutdown",
            ],
        ),
    ],
)
def test_runtime_stage_failure_stops_everything_and_fails_loud(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_at: str,
    expected_runtime_events: list[str],
) -> None:
    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    docker = FakeDocker()
    runtime = FakeRuntime(failure_at)

    with pytest.raises(DevError, match=f"{failure_at} failed"):
        asyncio.run(
            run_dev(
                json_output=True,
                open_browser=False,
                docker=docker,
                ports=FreePorts(),
                runtime=runtime,
            )
        )

    assert runtime.events == expected_runtime_events
    assert docker.events == ["preflight", "up", "down"]


def test_signal_event_drives_graceful_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AwaitingRuntime(FakeRuntime):
        async def supervise(self, stop: asyncio.Event) -> None:
            self.record("supervise")
            await stop.wait()

    def install(stop: asyncio.Event) -> None:
        asyncio.get_running_loop().call_soon(stop.set)

    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dev_module, "_install_signal_handlers", install)
    docker = FakeDocker()
    runtime = AwaitingRuntime()

    asyncio.run(
        run_dev(
            json_output=True,
            open_browser=False,
            docker=docker,
            ports=FreePorts(),
            runtime=runtime,
        )
    )

    assert runtime.events[-2:] == ["supervise", "shutdown"]
    assert docker.events[-1] == "down"


def test_shutdown_failure_still_removes_runtime_auth_and_stops_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingShutdown(FakeRuntime):
        async def shutdown(self) -> None:
            self.record("shutdown")
            raise RuntimeError("shutdown failed")

    initialize(tmp_path)
    monkeypatch.chdir(tmp_path)
    docker = FakeDocker()

    with pytest.raises(RuntimeError, match="shutdown failed"):
        asyncio.run(
            run_dev(
                json_output=True,
                open_browser=False,
                docker=docker,
                ports=FreePorts(),
                runtime=FailingShutdown(),
            )
        )

    assert not (tmp_path / ".stateback/run/auth.json").exists()
    assert docker.events[-1] == "down"


def test_docker_preflight_distinguishes_stopped_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def command(
        arguments: tuple[str, ...], environment: Mapping[str, str] | None = None
    ) -> str:
        if arguments[:2] == ("docker", "info"):
            raise DockerError("cannot connect")
        return "available"

    monkeypatch.setattr(docker_module, "_command", command)

    with pytest.raises(DockerError, match="daemon is not running"):
        asyncio.run(LocalDockerRunner().preflight())


def test_port_checker_does_not_steal_occupied_port() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        with pytest.raises(DockerError, match=f"Port {port} is already in use"):
            SocketPortChecker().require_available("127.0.0.1", port, "API")


def test_dev_lock_rejects_a_second_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "dev.lock"
    with DevLock(lock_path, tmp_path):
        with pytest.raises(DevError, match="already running"):
            with DevLock(lock_path, tmp_path):
                pass


def test_supervisor_reports_child_exit_with_diagnostics(tmp_path: Path) -> None:
    async def scenario() -> None:
        supervisor = ProcessSupervisor(tmp_path, show_output=False)
        child = await supervisor.start("health", dict(os.environ))
        with pytest.raises(SupervisorError, match="health exited unexpectedly"):
            await supervisor.wait_for_exit_or_stop(asyncio.Event())
        await child.output_task
        assert any("Stateback:" in line for line in child.last_lines)
        await supervisor.shutdown()

    asyncio.run(scenario())


@pytest.mark.skipif(os.name != "posix", reason="POSIX signal semantics")
def test_supervisor_kills_process_that_ignores_termination(tmp_path: Path) -> None:
    async def scenario() -> None:
        supervisor = ProcessSupervisor(tmp_path, show_output=False)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, lambda *_: None); print('ready', flush=True); time.sleep(30)",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert process.stdout is not None
        assert await process.stdout.readline() == b"ready\n"

        async def drain() -> None:
            await process.communicate()

        child = Child("stubborn", process, asyncio.create_task(drain()))
        supervisor._children.append(child)
        await supervisor.shutdown(timeout=0.01)
        assert process.returncode == -signal.SIGKILL

    asyncio.run(scenario())
