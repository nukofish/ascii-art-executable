"""Preserve the old process-module imports during the public-module migration."""

import subprocess
import sys
from threading import Event
from time import monotonic
from unittest.mock import MagicMock, Mock, call

import pytest

from codeart import contracts, procutil
from codeart.contracts import RunContext
from codeart import _verification_process as legacy
from codeart.verify import VerificationContext


def test_legacy_process_imports_keep_type_identity():
    assert legacy.BuildSession is procutil.BuildSession
    assert legacy.WorkStopped is procutil.WorkStopped
    assert legacy.run_command is procutil.run_command
    assert legacy.VerificationContext is VerificationContext
    assert legacy._stop_process is procutil.stop_process


@pytest.mark.parametrize(("overall", "timeout", "stop_reason"), [
    (1.0, 0.03125, None),
    (0.015625, 0.03125, "PIPELINE_TIMEOUT"),
    (0.03125, 0.03125, "PIPELINE_TIMEOUT"),
    (0.03125, 0.03125, "CANCELLED"),
])
def test_command_stops_and_reaps_child_using_injected_clock(
    monkeypatch, tmp_path, overall, timeout, stop_reason,
):
    monkeypatch.setattr(contracts, "monotonic", lambda: 0.0)
    monkeypatch.setattr(procutil, "monotonic", lambda: 0.0)
    now = 0.0
    event = Event()
    ctx = RunContext(overall, event, clock=lambda: now)
    child = MagicMock()
    child.__enter__.return_value = child
    stop = Mock()
    monkeypatch.setattr(procutil.subprocess, "Popen", Mock(return_value=child))
    monkeypatch.setattr(procutil, "stop_process", stop)

    def communicate(*, timeout=None):
        nonlocal now
        if timeout is None:
            stop.assert_called_once_with(child)
            return b"partial stdout", b""
        now += timeout
        if stop_reason == "CANCELLED":
            event.set()
        raise subprocess.TimeoutExpired(["example"], timeout)

    child.communicate.side_effect = communicate
    expected_error = procutil.WorkStopped if stop_reason else procutil.CommandTimedOut
    with pytest.raises(expected_error) as error:
        procutil.run_command(["example"], cwd=tmp_path, env=None, ctx=ctx, timeout=timeout)

    assert child.communicate.call_args_list == [call(timeout=min(overall, timeout)), call()]
    if stop_reason:
        assert error.value.reason == stop_reason
    else:
        assert error.value.stdout == "partial stdout"


@pytest.mark.parametrize(("overall", "timeout", "error_type"), [
    (1.0, 0.1, procutil.CommandTimedOut),
    (0.1, 1.0, procutil.WorkStopped),
])
def test_frozen_clock_stops_and_reaps_real_child(
    monkeypatch, tmp_path, overall, timeout, error_type,
):
    popen = subprocess.Popen
    children = []

    def track_child(*args, **kwargs):
        child = popen(*args, **kwargs)
        # On Windows stop_process runs taskkill to stop the child's tree.
        if child.args[0] != "taskkill":
            children.append(child)
        return child

    monkeypatch.setattr(procutil.subprocess, "Popen", track_child)
    with pytest.raises(error_type) as error:
        procutil.run_command(
            [sys.executable, "-c", "import time; time.sleep(0.5)"],
            cwd=tmp_path, env=None, ctx=RunContext(100.0 + overall, clock=lambda: 100.0),
            timeout=timeout,
        )

    if error_type is procutil.WorkStopped:
        assert error.value.reason == "PIPELINE_TIMEOUT"
    assert len(children) == 1
    assert children[0].returncode not in (None, 0)


def test_timeout_stops_descendants_that_hold_the_pipes(tmp_path):
    # A compiler wrapper (a .cmd shim on Windows) starts its own child, which
    # inherits stdout. Killing only the wrapper would leave communicate()
    # waiting for the grandchild to exit.
    script = (
        "import subprocess, sys, time; "
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    started = monotonic()
    with pytest.raises(procutil.CommandTimedOut):
        procutil.run_command(
            [sys.executable, "-c", script], cwd=tmp_path, env=None,
            ctx=RunContext(monotonic() + 60), timeout=1.0,
        )
    assert monotonic() - started < 10
