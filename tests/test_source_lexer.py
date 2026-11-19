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


def test_lex_requests_reuse_one_unit_per_flag_set(monkeypatch):
    pytest.importorskip("clang.cindex")
    from codeart import _source_worker as worker

    monkeypatch.setattr(worker, "_LEX_UNITS", {})
    strict = ["-std=c11", "-pedantic-errors"]
    texts = ["a + +b", "x->y", "数 = 1;", "??(", "a +++ b"]

    def spellings(text, flags):
        reply = worker.reply_for({"mode": "lex", "text": text, "flags": flags})
        return [token["spelling"] for token in reply["tokens"]]

    reused = [spellings(text, strict) for text in texts]
    assert len(worker._LEX_UNITS) == 1
    fresh = []
    for text in texts:
        monkeypatch.setattr(worker, "_LEX_UNITS", {})
        fresh.append(spellings(text, strict))
    assert reused == fresh
    assert reused[0] == ["a", "+", "+", "b"]
    assert reused[4] == ["a", "++", "+", "b"]

    # A different flag set gets its own unit and its own lexing rules. Clang's
    # default for trigraphs depends on the target, so set it both ways.
    assert spellings("??(", strict + ["-ftrigraphs"]) == ["??("]
    assert spellings("??(", strict + ["-fno-trigraphs"]) == ["?", "?", "("]
    assert spellings("??(", strict + ["-ftrigraphs"]) == ["??("]
    assert len(worker._LEX_UNITS) == 3


def test_lex_unit_that_fails_to_reparse_is_replaced(monkeypatch):
    pytest.importorskip("clang.cindex")
    import clang.cindex as clang
    from codeart import _source_worker as worker

    monkeypatch.setattr(worker, "_LEX_UNITS", {})
    flags = ["-std=c11"]
    first = worker._lex_unit(clang, "input.c", flags, "first\n")
    real = clang.conf.lib

    class FailingLib:
        def __getattr__(self, name):
            return getattr(real, name)

        @staticmethod
        def clang_reparseTranslationUnit(*args):
            return 1

    monkeypatch.setattr(clang.conf, "lib", FailingLib(), raising=False)
    second = worker._lex_unit(clang, "input.c", flags, "second\n")
    assert second is not first
    assert worker._LEX_UNITS[tuple(flags)] is second
