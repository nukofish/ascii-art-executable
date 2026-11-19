"""Shared subprocess and temporary-build utilities for Parts A and E.

This module is the public process boundary between the two owners. Part A
(`codeart.source`, `codeart._source_lexer`) uses `run_command`, `BuildSession`,
`stop_process` and the stop exceptions. Part E (`codeart.verify`,
`codeart.verification_regression`) uses the same names plus `check_context`.
Neither owner imports the other's private modules: the former
`codeart._verification_process` path is a compatibility shim only.

Every helper takes the caller's `RunContext`-compatible object, so one
monotonic deadline and one cancellation event govern both stages. Children
start in their own session on POSIX; the caller that owns the child reaps it
after `stop_process`.
"""

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

__all__ = (
    "BuildFailed", "BuildSession", "CommandTimedOut", "DependencyUnavailable",
    "WorkStopped", "check_context", "run_command", "stop_process",
)


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
    if ctx.remaining_s() <= 0:
        raise WorkStopped("PIPELINE_TIMEOUT")


class _WindowsJob:
    """A job object holding one child and every process it starts.

    TerminateProcess stops only the child. A wrapper such as a .cmd compiler
    shim leaves descendants that keep the pipes open, so `run_command` puts
    each child in a job and `stop_process` ends the whole job at once.
    """

    def __init__(self, proc):
        import ctypes
        from ctypes import wintypes

        self._kernel32 = kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = kernel32.CreateJobObjectW(None, None)
        if self.handle and not kernel32.AssignProcessToJobObject(self.handle, int(proc._handle)):
            self.close()

    def terminate(self):
        if self.handle:
            self._kernel32.TerminateJobObject(self.handle, 1)

    def close(self):
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def stop_process(proc: subprocess.Popen | None) -> None:
    """Kill a child and its descendants. The caller reaps the child."""
    if proc is None or proc.pid is None:
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            job = getattr(proc, "_codeart_job", None)
            if job is not None:
                job.terminate()
            proc.kill()
    except ProcessLookupError:
        pass


def run_command(args, *, cwd: Path, env, ctx, timeout: float):
    """Run one child under the caller's budget and return its captured output.

    The effective limit is the smaller of the stage `timeout` and the time left
    on `ctx`. Starting a missing program raises `DependencyUnavailable`; a
    cancelled or expired shared context raises `WorkStopped`; an exhausted
    stage budget raises `CommandTimedOut`. In every non-zero exit case the
    child's process group is killed before the exception leaves this function.
    """
    check_context(ctx)
    deadline = ctx.clock() + timeout
    real_deadline = monotonic() + timeout
    try:
        proc = subprocess.Popen(
            args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise DependencyUnavailable(str(exc)) from exc
    job = None
    if os.name == "nt" and isinstance(getattr(proc, "_handle", None), int):
        # The child joins the job a moment after it starts, before a wrapper
        # such as cmd.exe has had time to start a compiler of its own.
        job = proc._codeart_job = _WindowsJob(proc)
    try:
        return _wait_for(proc, args, ctx, deadline, real_deadline)
    finally:
        if job is not None:
            job.close()


def _wait_for(proc, args, ctx, deadline, real_deadline):
    with proc:
        try:
            while True:
                check_context(ctx)
                remaining = min(ctx.remaining_s(), deadline - ctx.clock(),
                                real_deadline - monotonic())
                if remaining <= 0:
                    break
                try:
                    stdout, stderr = proc.communicate(timeout=min(remaining, 0.05))
                except subprocess.TimeoutExpired:
                    continue
                check_context(ctx)
                if ctx.clock() >= deadline or monotonic() >= real_deadline:
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


# Windows linkers add .exe to an output name that has no extension.
_PROGRAM_NAME = "program.exe" if os.name == "nt" else "program"


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
        """Resolve, version and fingerprint the compiler once per session."""
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
            artifact = directory / ("input.o" if mode == "object" else _PROGRAM_NAME)
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
