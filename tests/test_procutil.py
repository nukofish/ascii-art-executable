"""Preserve the old process-module imports during the public-module migration."""

import subprocess
from threading import Event
from unittest.mock import MagicMock, Mock, call

import pytest

from codeart import procutil
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
