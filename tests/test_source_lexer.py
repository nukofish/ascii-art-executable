"""Reusable lexer lifecycle, concurrent requests and hung-worker recovery."""

from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

import pytest

from codeart.contracts import ErrorCode, StageError
from codeart._source_lexer import LexWorker


def payload(name):
    return {"mode": "lex", "text": name, "flags": ["-std=c11", "-pedantic-errors"]}


def test_worker_reuse_serialization_and_restart():
    worker = LexWorker()
    try:
        assert worker.request(payload("first"), 5)["tokens"][0]["spelling"] == "first"
        process = worker._process
        with ThreadPoolExecutor(max_workers=4) as executor:
            names = ["a", "b", "c", "d"]
            replies = list(executor.map(lambda name: worker.request(payload(name), 5), names))
        assert [reply["tokens"][0]["spelling"] for reply in replies] == names
        assert worker._process is process
        worker.close()
        assert process.poll() is not None
        assert worker.request(payload("next"), 5)["tokens"][0]["spelling"] == "next"
        assert worker._process is not process
    finally:
        worker.close()


def test_hung_worker_is_reaped_and_next_request_recovers(monkeypatch):
    worker = LexWorker()
    processes = []
    real_popen = subprocess.Popen

    def hung_popen(args, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)
        processes.append(process)
        return process

    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", hung_popen)
            with pytest.raises(StageError) as exc:
                worker.request(payload("a"), 0.2)
        assert exc.value.diagnostic.code == ErrorCode.ANALYSIS_TIMEOUT
        assert processes[0].poll() is not None
        assert worker._process is None
        assert worker.request(payload("recovered"), 5)["tokens"][0]["spelling"] == "recovered"
    finally:
        worker.close()
