"""Docker and local-port boundaries for the development orchestrator."""

from __future__ import annotations

import asyncio
import os
import socket
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol


class DockerError(RuntimeError):
    """Docker cannot safely provide the requested local infrastructure."""


class DockerRunner(Protocol):
    async def preflight(self) -> None: ...

    async def compose_up(
        self, *, project: str, compose_file: Path, environment: Mapping[str, str]
    ) -> None: ...

    async def compose_down(
        self, *, project: str, compose_file: Path, environment: Mapping[str, str]
    ) -> None: ...


class PortChecker(Protocol):
    def require_available(self, host: str, port: int, service: str) -> None: ...


async def _command(
    arguments: Sequence[str], environment: Mapping[str, str] | None = None
) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=None if environment is None else dict(environment),
        )
    except FileNotFoundError as exc:
        raise DockerError(
            "Stateback requires Docker for local PostgreSQL and NATS services.\n\n"
            "Install Docker and run:\n  stateback dev"
        ) from exc
    output, _ = await process.communicate()
    text = output.decode(errors="replace").strip()
    if process.returncode != 0:
        raise DockerError(text or f"command failed: {' '.join(arguments)}")
    return text


class LocalDockerRunner:
    async def preflight(self) -> None:
        await _command(("docker", "--version"))
        try:
            await _command(("docker", "compose", "version", "--short"))
        except DockerError as exc:
            raise DockerError(
                "Docker Compose is unavailable. Install the Docker Compose plugin "
                "and run:\n  stateback dev"
            ) from exc
        try:
            await _command(("docker", "info", "--format", "{{.ServerVersion}}"))
        except DockerError as exc:
            raise DockerError(
                "Docker was found, but the Docker daemon is not running.\n\n"
                "Start Docker Desktop and run:\n  stateback dev"
            ) from exc

    async def compose_up(
        self, *, project: str, compose_file: Path, environment: Mapping[str, str]
    ) -> None:
        await _command(
            (
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_file),
                "up",
                "-d",
                "--wait",
            ),
            environment,
        )

    async def compose_down(
        self, *, project: str, compose_file: Path, environment: Mapping[str, str]
    ) -> None:
        await _command(
            (
                "docker",
                "compose",
                "-p",
                project,
                "-f",
                str(compose_file),
                "down",
            ),
            environment,
        )


class SocketPortChecker:
    def require_available(self, host: str, port: int, service: str) -> None:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as candidate:
            candidate.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                candidate.bind((host, port))
            except OSError as exc:
                raise DockerError(
                    f"Port {port} is already in use.\n\n"
                    f"Stateback's local {service} is configured to use {port}.\n\n"
                    "Change it in stateback.toml and run:\n  stateback dev"
                ) from exc


def compose_environment(
    *, postgres_port: int, nats_port: int, monitor_port: int
) -> dict[str, str]:
    environment = dict(os.environ)
    environment.update(
        {
            "STATEBACK_POSTGRES_PORT": str(postgres_port),
            "STATEBACK_NATS_PORT": str(nats_port),
            "STATEBACK_NATS_MONITOR_PORT": str(monitor_port),
        }
    )
    return environment
