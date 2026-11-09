"""Shared subprocess and temporary build utilities for A and E."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from time import monotonic

from .contracts import CompilerInfo


class WorkStopped(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class DependencyUnavailable(Exception):
    pass


class CommandTimedOut(Exception):
    def __init__(self, stdout: str):
        self.stdout = stdout
        super().__init__("Command exceeded its stage budget")


def check_context(ctx) -> None:
    if ctx.cancel_event is not None and ctx.cancel_event.is_set():
        raise WorkStopped("CANCELLED")
    if monotonic() >= ctx.deadline:
        raise WorkStopped("PIPELINE_TIMEOUT")


def stop_process(proc: subprocess.Popen) -> None:
    """Kill a child started in its own session. The caller reaps it."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass


def run_command(args, *, cwd: Path, env, ctx, timeout: float):
    check_context(ctx)
    deadline = monotonic() + timeout
    try:
        proc = subprocess.Popen(
            args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise DependencyUnavailable(str(exc)) from exc
    with proc:
        try:
            while True:
                check_context(ctx)
                remaining = min(deadline, ctx.deadline) - monotonic()
                if remaining <= 0:
                    break
                try:
                    stdout, stderr = proc.communicate(timeout=min(remaining, 0.05))
                except subprocess.TimeoutExpired:
                    continue
                check_context(ctx)
                if monotonic() >= deadline:
                    raise CommandTimedOut(stdout.decode("utf-8", errors="replace"))
                return subprocess.CompletedProcess(
                    args, proc.returncode,
                    stdout.decode("utf-8", errors="replace"),
                    stderr.decode("utf-8", errors="replace"),
                )
        except BaseException:
            stop_process(proc)
            proc.communicate()
            raise
        stop_process(proc)
        stdout, _ = proc.communicate()
        check_context(ctx)
        raise CommandTimedOut(stdout.decode("utf-8", errors="replace"))


class BuildFailed(Exception):
    def __init__(self, result: subprocess.CompletedProcess):
        self.result = result
        super().__init__("Compiler returned a nonzero exit status")


class BuildSession:
    """Owns build files and caches for one verify call or serial regression."""

    def __init__(self):
        self._directory = TemporaryDirectory(prefix="codeart-verify-")
        self.root = Path(self._directory.name)
        self.env = dict(os.environ, LC_ALL="C")
        self.counts = Counter(object=0, original=0, rendered=0)
        self._versions = {}
        self._artifacts = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._directory.cleanup()

    def compiler_info(self, profile, ctx) -> CompilerInfo:
        check_context(ctx)
        path = shutil.which(profile.compiler, path=self.env.get("PATH"))
        if path is None:
            raise DependencyUnavailable(f"Compiler not found: {profile.compiler}")
        path = os.path.abspath(path)
        try:
            stat = os.stat(path)
        except OSError as exc:
            raise DependencyUnavailable(str(exc)) from exc
        fingerprint = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        key = path, fingerprint
        if key not in self._versions:
            result = run_command(
                [path, "--version"], cwd=self.root, env=self.env, ctx=ctx,
                timeout=profile.compile_timeout,
            )
            if result.returncode != 0 or not result.stdout.strip():
                raise DependencyUnavailable(f"Cannot identify compiler: {path}")
            self._versions[key] = result.stdout.strip()
        return CompilerInfo(path, self._versions[key], tuple(profile.flags), fingerprint)

    def build(self, mode, source, wrapper, *, compiler, ctx, timeout) -> Path:
        check_context(ctx)
        key = (mode, compiler, source, wrapper)
        if mode != "rendered" and key in self._artifacts:
            return self._artifacts[key]
        directory = Path(mkdtemp(dir=self.root))
        try:
            source_path = directory / "input.c"
            source_path.write_text(source + wrapper, encoding="utf-8", newline="")
            artifact = directory / ("input.o" if mode == "object" else "program")
            args = [compiler.path, *compiler.flags]
            if mode == "object":
                args.append("-c")
            args.extend([str(source_path), "-o", str(artifact)])
            self.counts[mode] += 1
            result = run_command(args, cwd=directory, env=self.env, ctx=ctx, timeout=timeout)
            if result.returncode != 0 or not artifact.is_file():
                raise BuildFailed(result)
        except BaseException:
            shutil.rmtree(directory)
            raise
        if mode != "rendered":
            self._artifacts[key] = artifact
        return artifact

    def execute(self, program, *, ctx, timeout):
        return run_command([str(program)], cwd=program.parent, env=self.env,
                           ctx=ctx, timeout=timeout)
