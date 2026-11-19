"""Validate self-contained C11 functions and preserve raw lexical boundaries."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import monotonic

from .contracts import (
    Diagnostic, ErrorCode, LexedToken, RunContext, SourceModel, StageError, Token,
    VerificationProfile, grid_text, is_grid_character,
)
from ._source_lexer import LexWorker
from .procutil import (
    BuildFailed, BuildSession, CommandTimedOut, DependencyUnavailable, WorkStopped, run_command,
)

__all__ = ("analyze_program", "analyze_source", "can_join", "lex_source", "prepare_profile")

# Coordinates reported for the original text; the worker reports the same
# one-based convention after normalization.
_TRIGRAPH = re.compile(r"\?\?[=/'()!<>-]")
_LINE_SPLICE = re.compile(r"\\\n")
_COMPILER_ERROR = re.compile(r"input\.c:(\d+):(\d+): (?:fatal )?error:")
_COMMENT_OR_LITERAL = re.compile(
    r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.S,
)
_DIRECTIVE_START = re.compile(r"^[ \t]*(?:#|%:)[ \t]*([A-Za-z_]\w*)")


def _position(text, offset):
    """Return one-based line and column for an offset in the original text."""
    return text.count("\n", 0, offset) + 1, offset - text.rfind("\n", 0, offset)


class _AnalysisContext:
    """Keep one analysis deadline while retaining the caller's stop semantics."""

    def __init__(self, parent, timeout):
        self.parent = parent
        self.budget = RunContext.within(parent, timeout)
        self.clock = self.budget.clock
        self.deadline = self.budget.deadline
        self.cancel_event = self.budget.cancel_event

    def remaining_s(self):
        return self.budget.remaining_s()

    def check(self):
        self.parent.check()
        if self.remaining_s() <= 0:
            raise StageError(Diagnostic(
                ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Clang analysis timed out"
            ))


def _unsupported(message, line=None, column=None):
    return StageError(Diagnostic(ErrorCode.UNSUPPORTED_SOURCE, "analysis", message, line, column))


def _normalize(text, ctx):
    """Reject characters and phases the layout cannot reproduce, then use LF."""
    for line, content in enumerate(text.splitlines(keepends=True), 1):
        ctx.check()
        for column, char in enumerate(content, 1):
            # Printable ASCII plus the accepted newline forms and out-of-token tabs.
            if char not in "\r\n\t" and not " " <= char <= "~":
                raise _unsupported("Only printable ASCII source is supported", line, column)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for pattern, message in (
        (_LINE_SPLICE, "Line splicing is unsupported"),
        (_TRIGRAPH, "Trigraphs are unsupported"),
    ):
        match = pattern.search(text)
        if match:
            line, column = _position(text, match.start())
            raise _unsupported(message, line, column)
    return text


def _program_preamble(text):
    """Collect directives and complete conditional groups for the file prefix."""
    masked = _COMMENT_OR_LITERAL.sub(
        lambda match: "".join("\n" if char == "\n" else " " for char in match.group()),
        text,
    )
    lines = text.splitlines(keepends=True)
    masked_lines = masked.splitlines(keepends=True)
    ranges = []
    conditional_start = None
    conditional_depth = 0
    conditional_has_code = False
    code_seen = False
    index = 0

    while index < len(lines):
        match = _DIRECTIVE_START.match(masked_lines[index])
        if match is None:
            if masked_lines[index].strip():
                if conditional_depth:
                    conditional_has_code = True
                else:
                    code_seen = True
            index += 1
            continue
        end = index + 1
        while end < len(lines) and lines[end - 1].rstrip("\n").endswith("\\"):
            end += 1

        directive = match.group(1).lower()
        if conditional_depth == 0 and code_seen and directive in ("pragma", "line", "undef"):
            raise _unsupported(
                f"#{directive} after program code cannot be moved safely; "
                "move it before the first declaration",
                index + 1, 1,
            )
        if directive in ("if", "ifdef", "ifndef"):
            if conditional_depth == 0:
                conditional_start = index
                conditional_has_code = False
            conditional_depth += 1
        elif directive == "endif" and conditional_depth:
            conditional_depth -= 1
            if conditional_depth == 0:
                if conditional_has_code and code_seen:
                    # Moving guarded code ahead of earlier code is only checked
                    # for the default macros and can break other configurations.
                    raise _unsupported(
                        "A conditional block containing code after program code "
                        "cannot be moved safely; move the #if block before the "
                        "first declaration or remove the condition",
                        conditional_start + 1, 1,
                    )
                ranges.append((conditional_start, end))
                conditional_start = None
                code_seen = code_seen or conditional_has_code
        elif conditional_depth == 0:
            ranges.append((index, end))
        index = end

    preamble_lines = {
        line for start, end in ranges for line in range(start + 1, end + 1)
    }
    chunks = ["".join(lines[start:end]) for start, end in ranges]
    preamble = "".join(
        chunk if chunk.endswith("\n") else chunk + "\n" for chunk in chunks
    )
    return preamble, preamble_lines


def _normalize_program(text, ctx):
    """Keep preprocessing continuations intact while rejecting code splices."""
    for line, content in enumerate(text.splitlines(keepends=True), 1):
        ctx.check()
        for column, char in enumerate(content, 1):
            if char not in "\r\n\t" and not is_grid_character(char):
                raise _unsupported("Only printable, non-combining source characters are supported",
                                   line, column)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    match = _TRIGRAPH.search(text)
    if match:
        line, column = _position(text, match.start())
        raise _unsupported("Trigraphs are unsupported", line, column)
    _, preamble_lines = _program_preamble(text)
    for match in _LINE_SPLICE.finditer(text):
        line, column = _position(text, match.start())
        if line not in preamble_lines:
            raise _unsupported("Line splicing is unsupported outside preserved sections",
                               line, column)
    return text


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


def _first_compiler_error(stderr):
    """Locate the first error the compiler reported for the temporary input."""
    match = _COMPILER_ERROR.search(stderr or "")
    if match is None:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _check_object(text, profile, ctx):
    """Compile the original source as an object without linking."""
    try:
        with BuildSession() as builds:
            compiler = builds.compiler_info(profile, ctx)
            builds.build("object", text if text.endswith("\n") else text + "\n", "",
                         compiler=compiler, ctx=ctx, timeout=profile.compile_timeout)
    except BuildFailed as exc:
        line, column = _first_compiler_error(exc.result.stderr)
        raise StageError(Diagnostic(
            ErrorCode.INVALID_SOURCE, "analysis", "Input failed C11 object compilation",
            line, column, {"stderr": exc.result.stderr},
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
    """Validate one self-contained C11 function and return its raw token stream.

    Raises `StageError` with a shared `Diagnostic`. Text is checked before any
    child process starts, so unsupported characters, line splices and trigraphs
    report original line and column even when libclang is unavailable.
    """
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
        target = comments if raw["is_comment"] else tokens
        target.append(Token(len(target), raw["kind"], raw["spelling"],
                            len(raw["spelling"]), raw["line"], raw["column"]))
    return SourceModel(text, normalized, tuple(tokens), profile,
                       reply["function_name"], reply["signature"], tuple(comments))


def _program_profile(profile, ctx):
    flags = (*profile.flags, "-Wno-strict-prototypes")
    try:
        if not any(flag == "-resource-dir" or flag.startswith("-resource-dir=") for flag in flags):
            # The wheel ships libclang separately from Clang's built-in headers.
            resource = run_command(
                [profile.compiler, *flags, "-print-resource-dir"],
                cwd=Path.cwd(), env=None, ctx=ctx, timeout=profile.lex_timeout,
            )
            resource_dir = resource.stdout.strip()
            if resource.returncode != 0 or not resource_dir:
                raise DependencyUnavailable("Cannot locate Clang's resource directory")
            flags += ("-resource-dir", resource_dir)
    except DependencyUnavailable as exc:
        raise StageError(Diagnostic(ErrorCode.DEPENDENCY_UNAVAILABLE, "analysis", str(exc))) from exc
    except CommandTimedOut as exc:
        raise StageError(Diagnostic(
            ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Clang resource directory lookup timed out"
        )) from exc
    except WorkStopped as exc:
        ctx.check()
        raise StageError(Diagnostic(ErrorCode(exc.reason), "analysis", str(exc))) from exc

    if sys.platform == "darwin" and "-isysroot" not in flags:
        sdkroot = os.environ.get("SDKROOT")
        if not sdkroot:
            try:
                sdk = run_command(
                    ["xcrun", "--show-sdk-path"],
                    cwd=Path.cwd(), env=None, ctx=ctx, timeout=profile.lex_timeout,
                )
                if sdk.returncode == 0:
                    sdkroot = sdk.stdout.strip()
            except DependencyUnavailable:
                pass
            except CommandTimedOut as exc:
                raise StageError(Diagnostic(
                    ErrorCode.ANALYSIS_TIMEOUT, "analysis", "Clang SDK lookup timed out"
                )) from exc
            except WorkStopped as exc:
                ctx.check()
                raise StageError(Diagnostic(ErrorCode(exc.reason), "analysis", str(exc))) from exc
        if sdkroot:
            flags += ("-isysroot", sdkroot)
    return prepare_profile(replace(profile, flags=flags))


def analyze_program(text: str, profile: VerificationProfile | None = None, *, ctx=None):
    """Analyze a complete C11 translation unit while separating its raw prefix."""
    profile = profile or VerificationProfile()
    ctx = ctx or RunContext(monotonic() + profile.lex_timeout)
    ctx = _AnalysisContext(ctx, profile.lex_timeout)
    normalized = _normalize_program(text, ctx)
    profile = _program_profile(profile, ctx)
    reply = _check_reply(_invoke("program", normalized, profile, ctx))
    _check_object(normalized, profile, ctx)
    preamble, preamble_lines = _program_preamble(normalized)
    tokens = []
    comments = []
    for raw in reply["tokens"]:
        ctx.check()
        if raw["line"] in preamble_lines:
            continue
        target = comments if raw["is_comment"] else tokens
        target.append(Token(len(target), raw["kind"], raw["spelling"],
                            len(grid_text(raw["spelling"])), raw["line"], raw["column"]))
    return SourceModel(
        text, normalized, tuple(tokens), profile, "", "", tuple(comments),
        program_mode=True, preamble_text=preamble, has_main=reply["has_main"],
    )


_join_worker = LexWorker()
_JOIN_BOUNDARIES = frozenset("()[]{},;")


@lru_cache(maxsize=4096)
def _can_join_cached(expected, flags, timeout):
    text = "".join(spelling for kind, spelling in expected)
    reply = _check_reply(_join_worker.request(
        {"mode": "lex", "text": text, "flags": list(flags)}, timeout,
    ))
    return tuple((token["kind"], token["spelling"]) for token in reply["tokens"]) == expected


def can_join(run_tokens, next_token, profile=None, *, checked_run=False):
    """Check that adjacent tokens keep their kinds and raw spellings.

    The production layout may set checked_run once Clang has classified the
    individual tokens and the contiguous run has passed each earlier join.
    """
    profile = profile or VerificationProfile()
    if not run_tokens:
        return True
    expected = tuple((token.kind, token.spelling) for token in (*run_tokens, next_token))
    if any(not spelling for kind, spelling in expected):
        raise ValueError("Token spellings must not be empty")

    flags = tuple(profile.flags)
    if not checked_run:
        return _can_join_cached(expected, flags, profile.lex_timeout)

    # An appended delimiter is also independent, except when a parenthesis
    # could complete a C trigraph (??( or ??)).
    if (next_token.kind == "PUNCTUATION" and next_token.spelling in _JOIN_BOUNDARIES
            and not (next_token.spelling in "()" and run_tokens[-1].spelling.endswith("?"))):
        return True

    # A standalone delimiter in the checked run cannot start a longer C token.
    # Keep it in the suffix and let Clang check everything from there onward.
    for index in range(len(expected) - 2, -1, -1):
        kind, spelling = expected[index]
        if kind == "PUNCTUATION" and spelling in _JOIN_BOUNDARIES:
            expected = expected[index:]
            break

    return _can_join_cached(expected, flags, profile.lex_timeout)
