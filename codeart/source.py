"""Validate self-contained C11 functions and preserve raw lexical boundaries."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import monotonic

from .contracts import (
    Diagnostic, ErrorCode, LexedToken, RunContext, SourceModel, StageError, Token,
    VerificationProfile,
)
from ._source_lexer import LexWorker
from ._verification_process import (
    BuildFailed, BuildSession, CommandTimedOut, DependencyUnavailable, WorkStopped, run_command,
)


class _AnalysisContext:
    """Keep one analysis deadline while retaining the caller's stop semantics."""

    def __init__(self, parent, timeout):
        self.parent = parent
        self.clock = parent.clock
        self.deadline = min(parent.deadline, self.clock() + timeout)
        self.cancel_event = parent.cancel_event

    def remaining_s(self):
        return max(0.0, self.deadline - self.clock())

    def check(self):
        self.parent.check()
        if self.remaining_s() == 0:
            raise StageError(Diagnostic(
                ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Clang analysis timed out"
            ))


def _unsupported(message, line=None, column=None):
    return StageError(Diagnostic(ErrorCode.UNSUPPORTED_SOURCE, "analysis", message, line, column))


def _normalize(text, ctx):
    for line, content in enumerate(text.splitlines(keepends=True), 1):
        ctx.check()
        for column, char in enumerate(content, 1):
            if char not in "\r\n\t" and not " " <= char <= "~":
                raise _unsupported("Only printable ASCII source is supported", line, column)
    match = re.search(r"\\(?:\r\n|\r|\n)|\?\?[=/'()!<>-]", text)
    if match:
        line = text.count("\n", 0, match.start()) + 1
        column = match.start() - text.rfind("\n", 0, match.start())
        raise _unsupported("Line splicing and trigraphs are unsupported", line, column)
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _invoke(mode, text, profile, ctx):
    """Run libclang in a child that can be killed and reaped by the parent."""
    ctx.check()
    with TemporaryDirectory(prefix="codeart-source-") as directory:
        root = Path(directory)
        payload = root / "request.json"
        payload.write_text(json.dumps({
            "mode": mode, "text": text, "flags": list(profile.flags),
        }), encoding="utf-8")
        try:
            result = run_command(
                [sys.executable, str(Path(__file__).with_name("_source_worker.py")), str(payload)],
                cwd=root, env=None, ctx=ctx, timeout=profile.lex_timeout,
            )
        except CommandTimedOut as exc:
            raise StageError(Diagnostic(
                ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Clang analysis timed out"
            )) from exc
        except DependencyUnavailable as exc:
            raise StageError(Diagnostic(
                ErrorCode.DEPENDENCY_UNAVAILABLE, "analysis", str(exc)
            )) from exc
        except WorkStopped as exc:
            # Preserve a caller's more specific stage deadline when available.
            ctx.check()
            raise StageError(Diagnostic(ErrorCode(exc.reason), "analysis", str(exc))) from exc
    if result.returncode:
        raise StageError(Diagnostic(
            ErrorCode.INTERNAL_ERROR, "analysis", "Clang worker failed",
            details={"stderr": result.stderr, "exit_code": result.returncode},
        ))
    return _check_reply(json.loads(result.stdout))


def _check_reply(reply):
    if "error" in reply:
        error = reply["error"]
        raise StageError(Diagnostic(
            ErrorCode(error["code"]), "analysis", error["message"],
            error.get("line"), error.get("column"),
        ))
    return reply


def _check_object(text, profile, ctx):
    try:
        with BuildSession() as builds:
            compiler = builds.compiler_info(profile, ctx)
            builds.build("object", text if text.endswith("\n") else text + "\n", "",
                         compiler=compiler, ctx=ctx, timeout=profile.compile_timeout)
    except BuildFailed as exc:
        raise StageError(Diagnostic(
            ErrorCode.INVALID_SOURCE, "analysis", "Input failed C11 object compilation",
            details={"stderr": exc.result.stderr},
        )) from exc
    except DependencyUnavailable as exc:
        raise StageError(Diagnostic(ErrorCode.DEPENDENCY_UNAVAILABLE, "analysis", str(exc))) from exc
    except CommandTimedOut as exc:
        raise StageError(Diagnostic(
            ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Input compilation timed out"
        )) from exc
    except WorkStopped as exc:
        ctx.check()
        raise StageError(Diagnostic(ErrorCode(exc.reason), "analysis", str(exc))) from exc


def lex_source(text: str, *, ctx: RunContext):
    """Yield raw tokens, including comments, for E's verification callback."""
    return _lex_with_profile(text, VerificationProfile(), ctx)


def _lex_with_profile(text, profile, ctx):
    reply = _invoke("lex", text, profile, ctx)
    return tuple(LexedToken(**token) for token in reply["tokens"])


def prepare_profile(profile: VerificationProfile) -> VerificationProfile:
    """Bind the same raw lexer options to A and E when none was supplied."""
    if profile.lex_source is not None:
        return profile

    def lex(text, *, ctx):
        return _lex_with_profile(text, profile, ctx)

    return replace(profile, lex_source=lex)


def analyze_source(text: str, profile: VerificationProfile | None = None, *, ctx=None):
    profile = prepare_profile(profile or VerificationProfile())
    ctx = ctx or RunContext(monotonic() + profile.lex_timeout)
    ctx = _AnalysisContext(ctx, profile.lex_timeout)
    normalized = _normalize(text, ctx)
    reply = _invoke("analyze", normalized, profile, ctx)
    _check_object(normalized, profile, ctx)
    tokens = []
    comments = []
    for raw in reply["tokens"]:
        ctx.check()
        if raw["is_comment"]:
            comments.append(Token(len(comments), raw["kind"], raw["spelling"],
                                  len(raw["spelling"]), raw["line"], raw["column"]))
        else:
            tokens.append(Token(len(tokens), raw["kind"], raw["spelling"],
                                len(raw["spelling"]), raw["line"], raw["column"]))
    return SourceModel(text, normalized, tuple(tokens), profile,
                       reply["function_name"], reply["signature"], tuple(comments))


_join_worker = LexWorker()


@lru_cache(maxsize=4096)
def _can_join_cached(expected, flags, timeout):
    text = "".join(spelling for kind, spelling in expected)
    reply = _check_reply(_join_worker.request(
        {"mode": "lex", "text": text, "flags": list(flags)}, timeout,
    ))
    return tuple((token["kind"], token["spelling"]) for token in reply["tokens"]) == expected


def can_join(run_tokens, next_token, profile=None):
    """Re-lex the complete contiguous run and compare kind and raw spelling."""
    profile = profile or VerificationProfile()
    if not run_tokens:
        return True
    expected = tuple((token.kind, token.spelling) for token in (*run_tokens, next_token))
    return _can_join_cached(expected, tuple(profile.flags), profile.lex_timeout)
