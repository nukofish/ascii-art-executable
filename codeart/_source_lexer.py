"""A bounded, serialized connection to the reusable raw-lexer child."""

import atexit
from pathlib import Path
from queue import Empty, Queue
import json
import os
import subprocess
import sys
from threading import Lock, Thread
from time import monotonic

from .contracts import Diagnostic, ErrorCode, StageError
from ._verification_process import _stop_process


class LexWorker:
    def __init__(self):
        self._lock = Lock()
        self._process = None
        atexit.register(self.close)

    def close(self):
        process = self._process
        self._process = None
        if process is not None:
            _stop_process(process)
            process.wait()
            process.stdin.close()
            process.stdout.close()

    def request(self, payload, timeout):
        deadline = monotonic() + timeout
        if not self._lock.acquire(timeout=max(0.0, timeout)):
            raise self._timeout()
        thread = None
        try:
            if self._process is None or self._process.poll() is not None:
                self.close()
                self._process = subprocess.Popen(
                    [sys.executable, str(Path(__file__).with_name("_source_worker.py")), "--serve"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    start_new_session=(os.name == "posix"),
                )
            process = self._process
            responses = Queue(maxsize=1)

            def exchange():
                try:
                    process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
                    process.stdin.flush()
                    line = process.stdout.readline()
                    if not line:
                        raise OSError("Lexer worker exited without a response")
                    responses.put(json.loads(line))
                except Exception as exc:
                    responses.put(exc)

            thread = Thread(target=exchange, daemon=True)
            thread.start()
            try:
                reply = responses.get(timeout=max(0.0, deadline - monotonic()))
            except Empty as exc:
                # Kill the child before joining a thread blocked on pipe I/O.
                _stop_process(process)
                process.wait()
                thread.join()
                self.close()
                raise self._timeout() from exc
            thread.join()
            if isinstance(reply, Exception):
                self.close()
                raise StageError(Diagnostic(
                    ErrorCode.DEPENDENCY_UNAVAILABLE, "analysis", str(reply)
                )) from reply
            if monotonic() >= deadline:
                raise self._timeout()
            return reply
        except OSError as exc:
            self.close()
            raise StageError(Diagnostic(
                ErrorCode.DEPENDENCY_UNAVAILABLE, "analysis", str(exc)
            )) from exc
        except BaseException:
            if self._process is not None:
                _stop_process(self._process)
                self._process.wait()
            if thread is not None:
                thread.join()
            self.close()
            raise
        finally:
            self._lock.release()

    @staticmethod
    def _timeout():
        return StageError(Diagnostic(
            ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Raw lexer request timed out"
        ))
