"""E's token, geometry, compile and behavior checks for rendered C11."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from dataclasses import replace
from itertools import zip_longest
import re
from time import monotonic

from ._verification_geometry import check_geometry
from .contracts import (
    CheckStatus,
    CompilerInfo,
    Diagnostic,
    ErrorCode,
    LexedToken,
    RunContext,
    StageError,
    TokenDiff,
    TokenLocation,
    VerificationProfile,
    VerificationReport,
)
from .procutil import (
    BuildFailed,
    BuildSession,
    CommandTimedOut,
    DependencyUnavailable,
    WorkStopped,
    check_context,
    run_command,
)
from .verification_fixtures import BUILTIN_FIXTURES, FixtureSelection


class VerificationContext(RunContext):
    """Use the shared budget API while preserving E's stop exceptions."""

    def check(self) -> None:
        try:
            super().check()
        except StageError as exc:
            raise WorkStopped(exc.diagnostic.code.value) from exc


class LexingError(Exception):
    """An adapter could not lex the rendered source at the given location."""

    def __init__(self, message, *, line=None, column=None):
        self.line = line
        self.column = column
        super().__init__(message)


@contextmanager
def _stage(report, name, ctx):
    start = monotonic()
    try:
        check_context(ctx)
        yield
        check_context(ctx)
    finally:
        report.durations[name] = monotonic() - start


def _skip(report, stage, code, message):
    report.skip_reasons[stage] = code.value
    report.diagnostics.append(Diagnostic(code, stage, message))


def _token_key(token):
    return token.kind, token.spelling


def _first_diff(expected, actual, ctx, key=_token_key):
    for index, (left, right) in enumerate(zip_longest(expected, actual)):
        check_context(ctx)
        if left is None:
            reason = "EXTRA_TOKEN"
        elif right is None:
            reason = "MISSING_TOKEN"
        elif key(left) == key(right):
            continue
        else:
            reason = "KIND_OR_SPELLING"
        expected_loc = (
            TokenLocation(
                left.kind, left.spelling,
                getattr(left, "source_line", getattr(left, "line", None)),
                getattr(left, "source_column", getattr(left, "column", None)),
            )
            if left is not None else None
        )
        actual_loc = (
            TokenLocation(right.kind, right.spelling, right.line, right.column)
            if right is not None else None
        )
        return TokenDiff(index, expected_loc, actual_loc, reason)
    return None


def _check_tokens(model, rendered, profile, ctx, report):
    if profile.lex_source is None:
        _skip(report, "token", ErrorCode.DEPENDENCY_UNAVAILABLE, "No C lexer was configured")
        return None
    lex_ctx = VerificationContext.within(ctx, profile.lex_timeout)
    try:
        tokens = []
        source_text = getattr(rendered, "artwork_source_text", None) or rendered.source_text
        for token in profile.lex_source(source_text, ctx=lex_ctx):
            check_context(lex_ctx)
            if not token.is_comment:
                tokens.append(token)
        check_context(lex_ctx)
    except StageError as exc:
        diagnostic = exc.diagnostic
        if diagnostic.code not in (ErrorCode.DEPENDENCY_UNAVAILABLE, ErrorCode.ANALYSIS_TIMEOUT):
            raise
        report.diagnostics.append(diagnostic)
        report.skip_reasons["token"] = diagnostic.code.value
        return None
    except (FileNotFoundError, DependencyUnavailable) as exc:
        _skip(report, "token", ErrorCode.DEPENDENCY_UNAVAILABLE, str(exc))
        return None
    except (WorkStopped, TimeoutError) as exc:
        check_context(ctx)
        if isinstance(exc, WorkStopped) and exc.reason != "PIPELINE_TIMEOUT":
            raise
        _skip(report, "token", ErrorCode.ANALYSIS_TIMEOUT, "Rendered source lexing timed out")
        return None
    except LexingError as exc:
        report.token_status = CheckStatus.FAIL
        report.diagnostics.append(Diagnostic(
            ErrorCode.TOKEN_MISMATCH, "token", str(exc), exc.line, exc.column,
        ))
        return None

    report.first_diff = _first_diff(model.tokens, tokens, ctx)
    if report.first_diff is None:
        report.token_status = CheckStatus.PASS
        return tokens

    report.token_status = CheckStatus.FAIL
    diff = report.first_diff
    location = diff.actual or diff.expected
    report.diagnostics.append(Diagnostic(
        ErrorCode.TOKEN_MISMATCH, "token", "Effective token sequence changed",
        location.line, location.column, {"index": diff.index, "reason": diff.reason},
    ))
    return None


# Layout necessarily moves code to other lines, so __LINE__ (and macros such as
# assert that expand it) would always differ, and the clock macros can change
# between the two preprocessor runs. Neutralise them for the comparison only;
# the rest of the expansion must still match exactly.
_PREPROCESS_FLAGS = (
    "-E", "-D__LINE__=0", "-D__DATE__=0", "-D__TIME__=0", "-D__TIMESTAMP__=0",
    "-Wno-builtin-macro-redefined",
)
_STRING_LITERAL = re.compile(r'(?:u8|[uUL])?"')


def _expanded_token_key(token):
    """Compare string literals without whitespace.

    Stringizing (`#x`, as in `assert`) copies the spacing between the argument
    tokens, which layout necessarily changes. The artwork tokens themselves are
    compared exactly first, so a whitespace-only difference in an expanded
    string can only come from that spacing.
    """
    if _STRING_LITERAL.match(token.spelling) and token.spelling.endswith('"'):
        return token.kind, "".join(token.spelling.split())
    return token.kind, token.spelling


_LINE_MARKER = re.compile(r'^# (\d+) "((?:[^"\\]|\\.)*)"')


def _preprocessed_tokens(source, profile, builds, compiler, ctx):
    """Return expanded tokens whose lines refer to the given source text.

    Tokens that come from included headers get line 0.
    """
    path = builds.root / "program.c"
    path.write_text(source if source.endswith("\n") else source + "\n",
                    encoding="utf-8", newline="")
    result = run_command(
        [compiler.path, *compiler.flags, *_PREPROCESS_FLAGS, str(path)],
        cwd=builds.root, env=builds.env, ctx=ctx, timeout=profile.compile_timeout,
    )
    if result.returncode != 0:
        raise BuildFailed(result)

    # Blank out line markers and remember which source line each output line has.
    lines = result.stdout.split("\n")
    origins = []
    in_source, source_line = False, 0
    for index, line in enumerate(lines):
        marker = _LINE_MARKER.match(line)
        if marker:
            in_source = marker.group(2) == str(path)
            source_line = int(marker.group(1))
            lines[index] = ""
            origins.append(0)
            continue
        origins.append(source_line if in_source else 0)
        source_line += 1

    lex_ctx = VerificationContext.within(ctx, profile.lex_timeout)
    return tuple(
        replace(token, line=origins[token.line - 1] if token.line <= len(origins) else 0)
        for token in profile.lex_source("\n".join(lines), ctx=lex_ctx)
        if not token.is_comment
    )


def _check_program_preprocessing(model, rendered, profile, ctx, report):
    """Ensure moving directives to the prefix leaves macro expansion unchanged."""
    try:
        with BuildSession() as builds:
            compiler = builds.compiler_info(profile, ctx)
            original = _preprocessed_tokens(
                model.original_source, profile, builds, compiler, ctx,
            )
            generated = _preprocessed_tokens(
                rendered.source_text, profile, builds, compiler, ctx,
            )
    except BuildFailed as exc:
        report.token_status = CheckStatus.FAIL
        report.diagnostics.append(Diagnostic(
            ErrorCode.TOKEN_MISMATCH, "token",
            "The generated program could not be preprocessed",
            details={"stderr": exc.result.stderr},
        ))
        return False
    except CommandTimedOut as exc:
        raise StageError(Diagnostic(
            ErrorCode.ANALYSIS_TIMEOUT, "token",
            "Preprocessor comparison exceeded its time budget",
        )) from exc
    except DependencyUnavailable as exc:
        raise StageError(Diagnostic(
            ErrorCode.DEPENDENCY_UNAVAILABLE, "token", str(exc),
        )) from exc
    diff = _first_diff(original, generated, ctx, _expanded_token_key)
    if diff is None:
        return True
    report.token_status = CheckStatus.FAIL
    report.first_diff = diff
    # Point at the user's own source; preprocessed columns are not meaningful.
    expected = diff.expected
    line = expected.line if expected is not None and expected.line > 0 else None
    found = diff.actual.spelling if diff.actual is not None else "end of program"
    wanted = expected.spelling if expected is not None else "end of program"
    report.diagnostics.append(Diagnostic(
        ErrorCode.TOKEN_MISMATCH, "token",
        "Moving the preprocessing lines to the top changed macro expansion: "
        f"expected {wanted!r} but found {found!r} after the move",
        line, None,
        {"index": diff.index, "reason": diff.reason},
    ))
    return False


def _compile(builds, mode, source, wrapper, profile, ctx, report):
    try:
        if report.compiler is None:
            report.compiler = builds.compiler_info(profile, ctx)
        return builds.build(mode, source, wrapper, compiler=report.compiler, ctx=ctx,
                            timeout=profile.compile_timeout)
    except DependencyUnavailable as exc:
        _skip(report, "compile", ErrorCode.DEPENDENCY_UNAVAILABLE, str(exc))
    except CommandTimedOut:
        report.compile_status = CheckStatus.FAIL
        report.diagnostics.append(Diagnostic(
            ErrorCode.COMPILE_TIMEOUT, "compile", "Compilation exceeded its time budget",
            details={"build": mode},
        ))
    except BuildFailed as exc:
        report.compile_status = CheckStatus.FAIL
        report.diagnostics.append(Diagnostic(
            ErrorCode.COMPILE_FAILED, "compile", str(exc),
            details={"build": mode, "exit_code": exc.result.returncode,
                     "stderr": exc.result.stderr},
        ))
    return None


def _behavior_failure(report, code, fixture, mode, index, message, **details):
    report.behavior_status = CheckStatus.FAIL
    details.update(program=mode, case_index=index)
    if index is not None:
        details["inputs"] = fixture.cases[index]
    report.diagnostics.append(Diagnostic(code, "behavior", message, details=details))


def _run_behavior(builds, mode, program, fixture, profile, ctx, report):
    try:
        result = builds.execute(program, ctx=ctx, timeout=profile.execution_timeout)
    except CommandTimedOut as exc:
        completed = exc.stdout.count("\n")
        index = completed if completed < len(fixture.cases) else None
        _behavior_failure(
            report, ErrorCode.EXECUTION_TIMEOUT, fixture, mode, index,
            "Behavior program exceeded its batch time budget",
        )
        return None
    except DependencyUnavailable as exc:
        _skip(report, "behavior", ErrorCode.DEPENDENCY_UNAVAILABLE, str(exc))
        return None

    lines = result.stdout.splitlines()
    values = []
    for line in lines[:len(fixture.cases)]:
        try:
            values.append(int(line))
        except ValueError:
            break
    if (result.returncode != 0 or len(lines) != len(fixture.cases)
            or len(values) != len(fixture.cases)):
        index = len(values) if len(values) < len(fixture.cases) else None
        _behavior_failure(
            report, ErrorCode.BEHAVIOR_MISMATCH, fixture, mode, index,
            "Behavior program failed to produce a successful eight-value batch",
            exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
        )
        return None
    return values


def _build_behavior_programs(builds, fixture, source, profile, ctx, report):
    programs = {}
    wrapper = fixture.wrapper()
    for mode, text in (("original", fixture.source), ("rendered", source)):
        program = _compile(builds, mode, text, wrapper, profile, ctx, report)
        if program is None:
            return None
        programs[mode] = program
    return programs


def _check_behavior(builds, fixture, programs, profile, ctx, report):
    results = []
    for mode, program in programs.items():
        values = _run_behavior(builds, mode, program, fixture, profile, ctx, report)
        if values is None:
            return
        results.append(values)
    original, rendered = results
    for index, (expected, actual) in enumerate(zip(original, rendered)):
        check_context(ctx)
        report.behavior_cases_compared += 1
        if expected != actual:
            _behavior_failure(
                report, ErrorCode.BEHAVIOR_MISMATCH, fixture, "rendered", index,
                "Generated function returned a different value", expected=expected, actual=actual,
            )
            return
    report.behavior_status = CheckStatus.PASS


def _selected_fixture(model, fixtures):
    if isinstance(fixtures, FixtureSelection):
        fixture = fixtures.fixture
        if (BUILTIN_FIXTURES.get(fixture.name) is fixture
                and model.original_source == fixture.source
                and model.function_name == fixture.name):
            return fixture
    return None


def verify(model, plan, rendered, fixtures, profile, *, ctx) -> VerificationReport:
    """Verify the actual output without modifying any pipeline artifact.

    A's model and the profile's lexer are trusted inputs. Only explicit builtin
    selections with exact matching source may enter the execution stage.
    """
    report = VerificationReport()
    stage = "token"
    try:
        with _stage(report, stage, ctx):
            tokens = _check_tokens(model, rendered, profile, ctx, report)
        if report.token_status == CheckStatus.FAIL:
            report.skip_reasons.update(
                geometry="TOKEN_NOT_PASS", compile="TOKEN_NOT_PASS", behavior="TOKEN_NOT_PASS",
            )
            return report
        if getattr(model, "program_mode", False) and report.token_status == CheckStatus.PASS:
            report.token_status = CheckStatus.NOT_RUN
            with _stage(report, stage, ctx):
                if not _check_program_preprocessing(model, rendered, profile, ctx, report):
                    report.skip_reasons.update(
                        geometry="TOKEN_NOT_PASS", compile="TOKEN_NOT_PASS",
                        behavior="TOKEN_NOT_PASS",
                    )
                    return report
                report.token_status = CheckStatus.PASS

        stage = "geometry"
        with _stage(report, stage, ctx):
            artwork = rendered
            artwork_source_text = getattr(rendered, "artwork_source_text", None)
            if artwork_source_text is not None:
                artwork = rendered.__class__(
                    source_text=artwork_source_text,
                    position_map=rendered.position_map,
                    coverage=rendered.coverage,
                    token_coverage=rendered.token_coverage,
                    comment_coverage=rendered.comment_coverage,
                    comment_cells=rendered.comment_cells,
                )
            report.geometry_metrics, issues = check_geometry(model, plan, artwork, tokens, ctx)
            report.geometry_status = CheckStatus.PASS
            if issues.reasons:
                report.geometry_status = CheckStatus.FAIL
                line, column = (None, None)
                if issues.first_cell is not None:
                    row, col = issues.first_cell
                    if row >= 0 and col >= 0:
                        line, column = row + 1, col + 1
                report.diagnostics.append(Diagnostic(
                    ErrorCode.GEOMETRY_MISMATCH, stage, "Rendered geometry violates the layout",
                    line, column, {"reasons": list(issues.reasons)},
                ))

        if report.token_status != CheckStatus.PASS:
            report.skip_reasons.update(compile="TOKEN_NOT_PASS", behavior="TOKEN_NOT_PASS")
            return report

        stage = "compile"
        fixture = _selected_fixture(model, fixtures)
        behavior_skip_reason = None
        if report.geometry_status != CheckStatus.PASS:
            behavior_skip_reason = "GEOMETRY_NOT_PASS"
        elif fixture is None:
            behavior_skip_reason = "NO_FIXTURE"
        elif plan.mask.width * plan.mask.height > profile.max_behavior_cells:
            behavior_skip_reason = "OUTPUT_TOO_LARGE"
        shared = fixtures._builds if fixture is not None else None
        session = nullcontext(shared) if shared is not None else BuildSession()
        programs = None
        with session as builds:
            with _stage(report, stage, ctx):
                mode = (
                    "rendered" if getattr(model, "program_mode", False)
                    and getattr(model, "has_main", False) else "object"
                )
                artifact = _compile(builds, mode, rendered.source_text, "", profile,
                                    ctx, report)
                if artifact is not None:
                    if behavior_skip_reason is None:
                        programs = _build_behavior_programs(
                            builds, fixture, rendered.source_text, profile, ctx, report,
                        )
                    if behavior_skip_reason is not None or programs is not None:
                        report.compile_status = CheckStatus.PASS

            stage = "behavior"
            if report.compile_status != CheckStatus.PASS:
                report.skip_reasons[stage] = "COMPILE_NOT_PASS"
            elif behavior_skip_reason is not None:
                report.skip_reasons[stage] = behavior_skip_reason
            else:
                with _stage(report, stage, ctx):
                    _check_behavior(builds, fixture, programs, profile, ctx, report)
    except (StageError, WorkStopped) as exc:
        diagnostic = (exc.diagnostic if isinstance(exc, StageError)
                      else Diagnostic(ErrorCode(exc.reason), stage, str(exc)))
        report.diagnostics.append(diagnostic)
        for name in ("token", "geometry", "compile", "behavior"):
            if getattr(report, f"{name}_status") == CheckStatus.NOT_RUN:
                report.skip_reasons.setdefault(name, diagnostic.code.value)
    except Exception as exc:
        _skip(report, stage, ErrorCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        for name in ("geometry", "compile", "behavior"):
            if getattr(report, f"{name}_status") == CheckStatus.NOT_RUN:
                report.skip_reasons.setdefault(name, ErrorCode.INTERNAL_ERROR.value)
    return report
