"""Bounded-log child-process supervision for the local composition."""

from __future__ import annotations

import asyncio
import sys
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


class SupervisorError(RuntimeError):
    """A supervised Stateback process failed."""


_MAX_LOG_BYTES = 1024 * 1024


@dataclass(slots=True)
class Child:
    name: str
    process: asyncio.subprocess.Process
    output_task: asyncio.Task[None]
    last_lines: deque[str] = field(default_factory=lambda: deque(maxlen=20))


class ProcessSupervisor:
    def __init__(self, log_directory: Path, *, show_output: bool = True) -> None:
        self._log_directory = log_directory
        self._show_output = show_output
        self._children: list[Child] = []

    async def start(
        self, name: str, environment: Mapping[str, str], *, command: str | None = None
    ) -> Child:
        log_path = self._log_directory / f"{name}.log"
        backup = log_path.with_suffix(".log.1")
        if log_path.exists() and log_path.stat().st_size >= _MAX_LOG_BYTES:
            backup.unlink(missing_ok=True)
            log_path.replace(backup)
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "stateback.cli.main",
            command or name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=dict(environment),
            cwd=str(self._log_directory.parent.parent),
        )
        assert process.stdout is not None
        child = Child(name, process, asyncio.create_task(asyncio.sleep(0)))
        child.output_task = asyncio.create_task(
            self._capture(child, process.stdout, log_path)
        )
        self._children.append(child)
        return child

    async def _capture(
        self,
        child: Child,
        stream: asyncio.StreamReader,
        log_path: Path,
    ) -> None:
        with log_path.open("ab") as log:
            while line := await stream.readline():
                decoded = line.decode(errors="replace").rstrip()
                child.last_lines.append(decoded)
                payload = (decoded + "\n").encode()
                remaining = _MAX_LOG_BYTES - log.tell()
                if len(payload) <= remaining:
                    log.write(payload)
                    log.flush()
                if self._show_output:
                    print(f"{child.name:<7} | {decoded}")

    @staticmethod
    def _assert_alive(child: Child) -> None:
        if child.process.returncode is not None:
            details = "\n".join(f"  {line}" for line in child.last_lines)
            suffix = f"\n\nLast log lines:\n{details}" if details else ""
            raise SupervisorError(
                f"Stateback {child.name} exited unexpectedly with code "
                f"{child.process.returncode}.{suffix}"
            )

    async def wait_for_marker(
        self, child: Child, marker: Path, timeout: float = 30
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            self._assert_alive(child)
            if marker.is_file():
                return
            await asyncio.sleep(0.1)
        raise SupervisorError(f"Stateback {child.name} did not become ready")

    async def wait_for_exit_or_stop(self, stop: asyncio.Event) -> None:
        stop_task = asyncio.create_task(stop.wait())
        waits = {
            asyncio.create_task(child.process.wait()): child for child in self._children
        }
        try:
            done, _ = await asyncio.wait(
                (stop_task, *waits), return_when=asyncio.FIRST_COMPLETED
            )
            if stop_task in done:
                return
            failed_task = next(task for task in done if task in waits)
            child = waits[failed_task]
            await child.output_task
            self._assert_alive(child)
        finally:
            stop_task.cancel()
            for task in waits:
                task.cancel()

    async def shutdown(self, timeout: float = 10) -> None:
        live = [child for child in self._children if child.process.returncode is None]
        for child in live:
            child.process.terminate()
        if live:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(child.process.wait() for child in live)), timeout
                )
            except TimeoutError:
                for child in live:
                    if child.process.returncode is None:
                        child.process.kill()
                await asyncio.gather(*(child.process.wait() for child in live))
        await asyncio.gather(
            *(child.output_task for child in self._children), return_exceptions=True
        )


async def run_one_shot(name: str, environment: Mapping[str, str]) -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "stateback.cli.main",
        name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=dict(environment),
    )
    output, _ = await process.communicate()
    if process.returncode != 0:
        diagnostic = output.decode(errors="replace").strip()
        raise SupervisorError(
            f"Stateback {name} failed" + (f": {diagnostic}" if diagnostic else "")
        )
