"""E's token, geometry, compile and behavior checks for rendered C11."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from itertools import zip_longest
from time import monotonic

from ._verification_geometry import check_geometry
from ._verification_process import (
    BuildFailed,
    BuildSession,
    CommandTimedOut,
    CompilerInfo,
    DependencyUnavailable,
    VerificationContext,
    WorkStopped,
    check_context,
)
from .contracts import (
    CheckStatus,
    Diagnostic,
    ErrorCode,
    LexedToken,
    TokenDiff,
    TokenLocation,
    VerificationProfile,
    VerificationReport,
)
from .verification_fixtures import BUILTIN_FIXTURES, FixtureSelection


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


def _first_diff(expected, actual, ctx):
    for index, (left, right) in enumerate(zip_longest(expected, actual)):
        check_context(ctx)
        if left is None:
            reason = "EXTRA_TOKEN"
        elif right is None:
            reason = "MISSING_TOKEN"
        elif (left.kind, left.spelling) == (right.kind, right.spelling):
            continue
        else:
            reason = "KIND_OR_SPELLING"
        expected_loc = (
            TokenLocation(left.kind, left.spelling, left.source_line, left.source_column)
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
    lex_ctx = VerificationContext(min(ctx.deadline, monotonic() + profile.lex_timeout),
                                  ctx.cancel_event)
    try:
        tokens = []
        for token in profile.lex_source(rendered.source_text, ctx=lex_ctx):
            check_context(lex_ctx)
            if not token.is_comment:
                tokens.append(token)
        check_context(lex_ctx)
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


def _compile(builds, mode, source, wrapper, profile, ctx, report, stage):
    try:
        if report.compiler is None:
            report.compiler = builds.compiler_info(profile, ctx)
        return builds.build(mode, source, wrapper, compiler=report.compiler, ctx=ctx,
                            timeout=profile.compile_timeout)
    except DependencyUnavailable as exc:
        _skip(report, stage, ErrorCode.DEPENDENCY_UNAVAILABLE, str(exc))
    except CommandTimedOut:
        setattr(report, f"{stage}_status", CheckStatus.FAIL)
        report.diagnostics.append(Diagnostic(
            ErrorCode.COMPILE_TIMEOUT, stage, "Compilation exceeded its time budget",
            details={"build": mode},
        ))
    except BuildFailed as exc:
        setattr(report, f"{stage}_status", CheckStatus.FAIL)
        report.diagnostics.append(Diagnostic(
            ErrorCode.COMPILE_FAILED, stage, str(exc),
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


def _check_behavior(builds, fixture, source, profile, ctx, report):
    results = []
    wrapper = fixture.wrapper()
    for mode, text in (("original", fixture.source), ("rendered", source)):
        program = _compile(builds, mode, text, wrapper, profile, ctx, report, "behavior")
        if program is None:
            return
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

        stage = "geometry"
        with _stage(report, stage, ctx):
            report.geometry_metrics, issues = check_geometry(model, plan, rendered, tokens, ctx)
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
        shared = fixtures._builds if fixture is not None else None
        session = nullcontext(shared) if shared is not None else BuildSession()
        with session as builds:
            with _stage(report, stage, ctx):
                artifact = _compile(builds, "object", rendered.source_text, "", profile,
                                    ctx, report, stage)
                if artifact is not None:
                    report.compile_status = CheckStatus.PASS

            stage = "behavior"
            if report.compile_status != CheckStatus.PASS:
                report.skip_reasons[stage] = "COMPILE_NOT_PASS"
            elif report.geometry_status != CheckStatus.PASS:
                report.skip_reasons[stage] = "GEOMETRY_NOT_PASS"
            elif fixture is None:
                report.skip_reasons[stage] = "NO_FIXTURE"
            elif plan.mask.width * plan.mask.height > profile.max_behavior_cells:
                report.skip_reasons[stage] = "OUTPUT_TOO_LARGE"
            else:
                with _stage(report, stage, ctx):
                    _check_behavior(builds, fixture, rendered.source_text, profile, ctx, report)
    except WorkStopped as exc:
        code = ErrorCode(exc.reason)
        report.diagnostics.append(Diagnostic(code, stage, str(exc)))
        for name in ("token", "geometry", "compile", "behavior"):
            if getattr(report, f"{name}_status") == CheckStatus.NOT_RUN:
                report.skip_reasons.setdefault(name, code.value)
    except Exception as exc:
        _skip(report, stage, ErrorCode.INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        for name in ("geometry", "compile", "behavior"):
            if getattr(report, f"{name}_status") == CheckStatus.NOT_RUN:
                report.skip_reasons.setdefault(name, ErrorCode.INTERNAL_ERROR.value)
    return report
