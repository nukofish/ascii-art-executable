"""E tests with real B masks and a test-only Clang raw-token adapter."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Thread
from time import monotonic, sleep

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codeart._verification_process import BuildSession, run_command, WorkStopped
from codeart.contracts import Diagnostic, RunContext, StageError
from codeart.shapes import FontMetrics, ShapeSpec, SizeRequest, build_mask, geometry_metrics
from codeart.verification_fixtures import BUILTIN_FIXTURES, select_builtin
from codeart.verification_regression import CatScaleReference, HoleReference, run_regression
from codeart.verify import (
    CheckStatus, ErrorCode, LexedToken, VerificationContext, VerificationProfile, verify,
)
from fixtures.verification_reports import make_verifier_stub


CLANG = shutil.which("clang")
requires_clang = pytest.mark.skipif(CLANG is None, reason="Clang is required")
_RAW_TOKEN = re.compile(r"(\w+) '(.*?)'\t[^\n]*\tLoc=<<stdin>:(\d+):(\d+)>\n", re.DOTALL)


def clang_lex_for_test(source, *, ctx):
    ctx.check()
    result = subprocess.run(
        [CLANG, "-std=c11", "-x", "c", "-fsyntax-only", "-Xclang", "-dump-raw-tokens", "-"],
        input=source, text=True, capture_output=True, check=True,
        timeout=max(0, ctx.deadline - monotonic()),
    )
    tokens = []
    offset = 0
    for match in _RAW_TOKEN.finditer(result.stderr):
        assert match.start() == offset, result.stderr
        offset = match.end()
        kind, spelling, line, column = match.groups()
        if kind == "unknown" and spelling.isspace():
            continue
        tokens.append(LexedToken(kind, spelling, int(line), int(column), kind == "comment"))
    assert offset == len(result.stderr), result.stderr
    return tokens


@dataclass(frozen=True)
class Token:
    index: int
    kind: str
    spelling: str
    width: int
    source_line: int
    source_column: int


@dataclass(frozen=True)
class Model:
    original_source: str
    function_name: str
    tokens: tuple[Token, ...]


@dataclass(frozen=True)
class Placement:
    token_index: int
    row: int
    col: int


@dataclass(frozen=True)
class Plan:
    mask: object
    placements: tuple[Placement, ...]
    protected_blanks: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class Rendered:
    source_text: str
    position_map: dict[int, tuple[int, int]]
    coverage: float
    token_coverage: float
    comment_coverage: float
    comment_cells: dict[str, int]


def context(seconds=30, event=None):
    return VerificationContext(monotonic() + seconds, event)


def profile(**options):
    return replace(VerificationProfile(clang_lex_for_test), **options)


def make_case(source, name, shape=ShapeSpec("circle"), *, height=32, fill=False, ctx=None):
    """Place complete fixture lines inside real masks, then add test filler."""
    ctx = ctx or context()
    lexed = clang_lex_for_test(source, ctx=ctx)
    tokens = tuple(Token(i, t.kind, t.spelling, len(t.spelling), t.line, t.column)
                   for i, t in enumerate(t for t in lexed if not t.is_comment))
    model = Model(source, name, tokens)
    mask = build_mask(shape, SizeRequest(height), FontMetrics(), ctx=ctx)
    canvas = [[" "] * mask.width for _ in range(mask.height)]
    line_placements = {}
    spans_by_row = {}
    first_row = 0
    if fill and shape.kind == "cat":
        first_row = max(row for row, _ in mask.features["ears"]) + 1
    candidates = iter(enumerate(mask.spans[first_row:], first_row))
    for line, text in enumerate(source.splitlines(), 1):
        if not text.strip():
            continue
        for row, spans in candidates:
            widest = max(spans, key=lambda span: span[1] - span[0], default=(0, 0))
            if widest[1] - widest[0] >= len(text):
                col = widest[0]
                canvas[row][col:col + len(text)] = text
                line_placements[line] = row, col
                spans_by_row[row] = (col, col + len(text))
                break
        else:
            raise AssertionError(f"Cannot fit test fixture line {text!r}")

    comment_cells = {"block": 0, "line": 0}
    if fill:
        for row, spans in enumerate(mask.spans):
            for start, end in spans:
                token_span = spans_by_row.get(row)
                if token_span is None or end <= token_span[0] or start >= token_span[1]:
                    gaps = [(start, end)]
                else:
                    gaps = [(start, token_span[0] - 1), (token_span[1] + 1, end)]
                for lo, hi in gaps:
                    width = hi - lo
                    if width >= 2 and hi == spans[-1][1]:
                        canvas[row][lo:hi] = "//" + "=" * (width - 2)
                        comment_cells["line"] += width
                    elif width >= 4:
                        canvas[row][lo:hi] = "/*" + "=" * (width - 4) + "*/"
                        comment_cells["block"] += width

    placements = []
    for token in tokens:
        row, col = line_placements[token.source_line]
        placements.append(Placement(token.index, row, col + token.source_column - 1))
    position_map = {p.token_index: (p.row, p.col) for p in placements}
    token_cells = sum(sum(ch != " " for ch in token.spelling) for token in tokens)
    comments = sum(comment_cells.values())
    allowed = sum(map(sum, mask.allowed))
    rendered = Rendered(
        "".join("".join(row).rstrip() + "\n" for row in canvas),
        position_map, (token_cells + comments) / allowed, token_cells / allowed,
        comments / allowed, comment_cells,
    )
    return model, Plan(mask, tuple(placements)), rendered


def statuses(report):
    return tuple(getattr(report, f"{name}_status").value
                 for name in ("token", "geometry", "compile", "behavior"))


def diagnostics(report):
    return {diag.code for diag in report.diagnostics}


def run(case, *, fixture=None, selected_profile=None, ctx=None):
    return verify(*case, fixture, selected_profile or profile(), ctx=ctx or context())


def test_fake_reports_are_injectable():
    expected = {
        "pass": ("PASS", "PASS", "PASS", "PASS"),
        "token_mismatch": ("FAIL", "PASS", "NOT_RUN", "NOT_RUN"),
        "hole_leakage": ("PASS", "FAIL", "PASS", "NOT_RUN"),
        "compiler_unavailable": ("PASS", "PASS", "NOT_RUN", "NOT_RUN"),
    }
    for name, values in expected.items():
        stub = make_verifier_stub(name)
        assert statuses(stub(None, None, None, None, None, ctx=context())) == values


@requires_clang
def test_real_compiler_and_builtin_behavior():
    fixture = select_builtin("max2")
    case = make_case(fixture.fixture.source, "max2", fill=True)
    report = run(case, fixture=fixture)
    assert statuses(report) == ("PASS",) * 4, report.diagnostics
    assert report.behavior_cases_compared == 8
    assert report.compiler.version
    assert report.geometry_metrics["coverage"] >= 0.85
    assert set(report.durations) == {"token", "geometry", "compile", "behavior"}


@requires_clang
@pytest.mark.parametrize(
    ("before", "after", "expected", "actual"),
    [
        ("x + +1", "x ++1", "+", "++"),
        ("x >= 0", "x > = 0", ">=", ">"),
        ("return ", "return return ", "x", "return"),
        ("return ", "//===== ", "return", None),
    ],
)
def test_token_changes_return_first_difference(before, after, expected, actual):
    body = before if before.startswith("x") else "x + +1"
    source = f"int f(int x) {{ return {body}; }}\n"
    model, plan, rendered = make_case(source, "f")
    changed = rendered.source_text.replace(before, after, 1)
    report = run((model, plan, replace(rendered, source_text=changed)))
    assert report.token_status == CheckStatus.FAIL, report.diagnostics
    assert report.compile_status == report.behavior_status == CheckStatus.NOT_RUN
    assert ErrorCode.TOKEN_MISMATCH in diagnostics(report)
    assert report.first_diff.expected.spelling == expected
    assert report.first_diff.expected.line == 1
    if actual is None:
        assert report.first_diff.actual is None
    else:
        assert report.first_diff.actual.spelling == actual
        row = next(i for i, line in enumerate(changed.splitlines(), 1) if after in line)
        assert report.first_diff.actual.line == row


@requires_clang
def test_extra_token_has_no_expected_location():
    model, plan, rendered = make_case("int f(void) { return 0; }\n", "f")
    changed = rendered.source_text.replace("}", "};")
    report = run((model, plan, replace(rendered, source_text=changed)))
    assert report.first_diff.expected is None
    assert report.first_diff.actual.spelling == ";"


@requires_clang
@pytest.mark.parametrize(("kind", "feature"), [("cat", "eye_left"), ("code", "code_strokes")])
def test_hole_leakage_keeps_independent_compile_result(kind, feature):
    source = "int f(void) { return 0; }\n"
    model, plan, rendered = make_case(source, "f", ShapeSpec(kind), fill=True)
    golden = json.loads((Path(__file__).parent / "fixtures" / "shapes"
                         / f"{kind}_32.json").read_text())
    cells = plan.mask.features[feature]
    row, col = next((r, c) for r, c in sorted(cells)
                    if all((r, c + offset) in cells for offset in range(4)))
    assert golden["rows"][row][col:col + 4] == "...."
    lines = rendered.source_text.split("\n")
    line = lines[row].ljust(col + 4)
    lines[row] = line[:col] + "/**/" + line[col + 4:]
    changed = replace(rendered, source_text="\n".join(lines))
    report = run((model, plan, changed))
    assert statuses(report) == ("PASS", "FAIL", "PASS", "NOT_RUN"), report.diagnostics
    assert report.geometry_metrics["hole_leakage_cells"] == 4
    assert report.geometry_metrics["out_of_bounds_cells"] == 4
    assert ErrorCode.GEOMETRY_MISMATCH in diagnostics(report)


@requires_clang
def test_d_metadata_and_protected_blanks_are_checked():
    model, plan, rendered = make_case("int f(void) { return 0; }\n", "f", fill=True)
    first = plan.placements[0]
    changed_plan = replace(plan, protected_blanks=frozenset({(first.row, first.col)}))
    changed = replace(rendered, position_map={}, coverage=0, comment_cells={})
    report = run((model, changed_plan, changed))
    reasons = report.diagnostics[0].details["reasons"]
    assert {"position_map", "reported_coverage", "reported_comment_cells",
            "protected_blank_filled"} <= set(reasons)
    assert report.geometry_metrics["coverage"] == rendered.coverage


@requires_clang
def test_invalid_filler_and_physical_line_endings():
    model, plan, rendered = make_case("int f(void) { return 0; }\n", "f", fill=True)
    changed = rendered.source_text.replace("//=", "//a", 1).rstrip("\n")
    report = run((model, plan, replace(rendered, source_text=changed)))
    assert report.geometry_status == CheckStatus.FAIL
    assert {"unexpected_filler", "missing_final_lf"} <= set(report.diagnostics[0].details["reasons"])


@requires_clang
def test_token_internal_space_counts_as_one_uncovered_cell():
    source = 'int f(int i) { return "a b"[i]; }\n'
    case = make_case(source, "f", fill=True)
    report = run(case)
    assert statuses(report) == ("PASS", "PASS", "PASS", "NOT_RUN"), report.diagnostics
    assert report.geometry_metrics["token_coverage"] == case[2].token_coverage


@requires_clang
def test_missing_dependencies_and_no_fixture(tmp_path):
    fixture = select_builtin("min2")
    case = make_case(fixture.fixture.source, "min2")
    missing_compiler = run(case, fixture=fixture,
                           selected_profile=profile(compiler=str(tmp_path / "missing")))
    assert statuses(missing_compiler) == ("PASS", "PASS", "NOT_RUN", "NOT_RUN")
    assert missing_compiler.skip_reasons["compile"] == "DEPENDENCY_UNAVAILABLE"
    assert ErrorCode.DEPENDENCY_UNAVAILABLE in diagnostics(missing_compiler)

    missing_lexer = run(case, selected_profile=VerificationProfile())
    assert statuses(missing_lexer) == ("NOT_RUN", "PASS", "NOT_RUN", "NOT_RUN")
    assert missing_lexer.skip_reasons["token"] == "DEPENDENCY_UNAVAILABLE"
    assert run(case).skip_reasons["behavior"] == "NO_FIXTURE"
    changed_model = replace(case[0], original_source=case[0].original_source + "\n")
    assert run((changed_model, *case[1:]), fixture=fixture).skip_reasons["behavior"] == "NO_FIXTURE"


@requires_clang
def test_lexer_callback_receives_shared_budget_api():
    event = Event()
    generation = RunContext(monotonic() + 30, event)
    case = make_case("int f(void) { return 0; }\n", "f")
    budgets = []

    def lex(source, *, ctx):
        assert ctx.cancel_event is event
        assert ctx.deadline < generation.deadline
        budgets.append(ctx.remaining_s())
        return clang_lex_for_test(source, ctx=ctx)

    report = run(case, selected_profile=profile(lex_source=lex, lex_timeout=5.0),
                 ctx=generation)
    assert statuses(report) == ("PASS", "PASS", "PASS", "NOT_RUN"), report.diagnostics
    assert len(budgets) == 1
    assert 0 < budgets[0] <= 5.0


@requires_clang
def test_lexer_timeout_keeps_geometry_result():
    case = make_case("int f(void) { return 0; }\n", "f")

    def timed_out(source, *, ctx):
        raise TimeoutError

    report = run(case, selected_profile=profile(lex_source=timed_out))
    assert statuses(report) == ("NOT_RUN", "PASS", "NOT_RUN", "NOT_RUN")
    assert report.skip_reasons["token"] == "ANALYSIS_TIMEOUT"


@requires_clang
@pytest.mark.parametrize("code", (ErrorCode.DEPENDENCY_UNAVAILABLE, ErrorCode.ANALYSIS_TIMEOUT))
def test_lexer_stage_error_preserves_diagnostic_and_checks_geometry(code):
    case = make_case("int f(void) { return 0; }\n", "f")
    diagnostic = Diagnostic(code, "analysis", "Lexer unavailable or timed out", 2, 7,
                            {"adapter": "clang"})

    def lex(source, *, ctx):
        raise StageError(diagnostic)

    report = run(case, selected_profile=profile(lex_source=lex))
    assert report.diagnostics == [diagnostic]
    assert statuses(report) == ("NOT_RUN", "PASS", "NOT_RUN", "NOT_RUN")
    assert report.skip_reasons == {
        "token": code.value, "compile": "TOKEN_NOT_PASS", "behavior": "TOKEN_NOT_PASS",
    }


@requires_clang
@pytest.mark.parametrize("code", (ErrorCode.CANCELLED, ErrorCode.PIPELINE_TIMEOUT))
def test_public_stop_preserves_completed_checks(code, monkeypatch):
    case = make_case("int f(void) { return 0; }\n", "f")
    diagnostic = Diagnostic(code, "pipeline", "Generation stopped", details={"at": "compile"})

    def compiler_info(self, profile, ctx):
        raise StageError(diagnostic)

    monkeypatch.setattr(BuildSession, "compiler_info", compiler_info)
    report = run(case)
    assert report.diagnostics == [diagnostic]
    assert statuses(report) == ("PASS", "PASS", "NOT_RUN", "NOT_RUN")
    assert report.skip_reasons == {"compile": code.value, "behavior": code.value}


@requires_clang
def test_large_canvas_still_compiles():
    fixture = select_builtin("sum_to_n")
    case = make_case(fixture.fixture.source, fixture.fixture.name, height=240)
    report = run(case, fixture=fixture)
    assert statuses(report) == ("PASS", "PASS", "PASS", "NOT_RUN"), report.diagnostics
    assert report.skip_reasons["behavior"] == "OUTPUT_TOO_LARGE"
    assert report.behavior_cases_compared == 0


@requires_clang
def test_bad_c_compilation_and_behavior_result(monkeypatch):
    bad_c = make_case("int f(void) { return undeclared; }\n", "f")
    report = run(bad_c)
    assert statuses(report) == ("PASS", "PASS", "FAIL", "NOT_RUN")
    assert ErrorCode.COMPILE_FAILED in diagnostics(report)
    assert "undeclared" in report.diagnostics[0].details["stderr"]

    original_execute = BuildSession.execute
    executions = []

    def execute(self, program, *, ctx, timeout):
        result = original_execute(self, program, ctx=ctx, timeout=timeout)
        executions.append(program)
        if len(executions) == 2:
            result.stdout = "99\n" + result.stdout.split("\n", 1)[1]
        return result

    monkeypatch.setattr(BuildSession, "execute", execute)
    fixture = select_builtin("gcd")
    report = run(make_case(fixture.fixture.source, "gcd"), fixture=fixture)
    assert statuses(report) == ("PASS", "PASS", "PASS", "FAIL"), report.diagnostics
    mismatch = report.diagnostics[-1]
    assert mismatch.code == ErrorCode.BEHAVIOR_MISMATCH
    assert mismatch.details["case_index"] == 0
    assert mismatch.details["inputs"] == (0, 0)
    assert report.behavior_cases_compared == 1


def write_compiler(path):
    path.write_text(f"#!{sys.executable}\n"
                    "import sys, time\n"
                    "if '--version' in sys.argv:\n"
                    "    print('test compiler 1')\n"
                    "else:\n"
                    "    time.sleep(20)\n")
    path.chmod(0o755)
    return str(path)


@requires_clang
def test_compile_stage_timeout_and_global_deadline(tmp_path):
    case = make_case("int f(void) { return 0; }\n", "f")
    compiler = write_compiler(tmp_path / "compiler")
    report = run(case, selected_profile=profile(compiler=compiler, compile_timeout=0.3))
    assert statuses(report) == ("PASS", "PASS", "FAIL", "NOT_RUN"), report.diagnostics
    assert ErrorCode.COMPILE_TIMEOUT in diagnostics(report)
    assert report.durations["compile"] < 3

    report = run(case, selected_profile=profile(compiler=compiler), ctx=context(0.5))
    assert statuses(report) == ("PASS", "PASS", "NOT_RUN", "NOT_RUN"), report.diagnostics
    assert ErrorCode.PIPELINE_TIMEOUT in diagnostics(report)
    assert report.skip_reasons["compile"] == "PIPELINE_TIMEOUT"


@requires_clang
def test_behavior_timeout_marks_case_index(monkeypatch):
    from codeart._verification_process import CommandTimedOut

    def execute(*args, **kwargs):
        raise CommandTimedOut("0\n1\n")

    monkeypatch.setattr(BuildSession, "execute", execute)
    fixture = select_builtin("max2")
    report = run(make_case(fixture.fixture.source, "max2"), fixture=fixture)
    assert statuses(report) == ("PASS", "PASS", "PASS", "FAIL"), report.diagnostics
    assert report.diagnostics[-1].code == ErrorCode.EXECUTION_TIMEOUT
    assert report.diagnostics[-1].details["case_index"] == 2


@requires_clang
def test_cancelled_verification():
    case = make_case("int f(void) { return 0; }\n", "f")
    cancelled = Event()
    cancelled.set()
    report = run(case, ctx=context(event=cancelled))
    assert statuses(report) == ("NOT_RUN",) * 4
    assert set(report.skip_reasons.values()) == {"CANCELLED"}


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group is required")
def test_running_process_group_is_cancelled(tmp_path):
    event = Event()
    started = tmp_path / "started"
    finished = tmp_path / "finished"
    child = ("import pathlib, sys, time; pathlib.Path(sys.argv[1]).touch(); "
             "time.sleep(.4); pathlib.Path(sys.argv[2]).touch()")
    parent = ("import subprocess, sys; "
              "subprocess.run([sys.executable, '-c', *sys.argv[1:]])")

    def cancel_when_running():
        until = monotonic() + 2
        while not started.exists() and monotonic() < until:
            sleep(.01)
        event.set()

    watcher = Thread(target=cancel_when_running)
    watcher.start()
    try:
        with pytest.raises(WorkStopped, match="CANCELLED"):
            run_command(
                [sys.executable, "-c", parent, child, str(started), str(finished)],
                cwd=tmp_path, env=None, ctx=context(event=event), timeout=5,
            )
    finally:
        watcher.join()
    assert started.exists()
    sleep(.5)
    assert not finished.exists()


@pytest.mark.parametrize("scale", (1, 2, 4))
def test_scaled_cat_retains_three_holes(scale):
    mask = build_mask(ShapeSpec("cat"), SizeRequest(32 * scale), FontMetrics())
    metrics = geometry_metrics(mask)
    assert len(metrics["holes"]) == 3
    for feature in ("eye_left", "eye_right", "nose"):
        assert mask.features[feature]
        assert all(not mask.allowed[row][col] for row, col in mask.features[feature])


@requires_clang
def test_full_matrix_with_test_layout_real_clang():
    roots = set()

    def generate(selection, shape, *, ctx):
        roots.add(selection._builds.root)
        fixture = selection.fixture
        return run(make_case(fixture.source, fixture.name, shape, fill=True, ctx=ctx),
                   fixture=selection, ctx=ctx)

    # Synthetic reference input exercises the comparison contract. The other
    # scales still require B's independent expected values and tolerances.
    reference = CatScaleReference(
        {"eye_left": HoleReference(43, (15.0, 20.0), 1),
         "eye_right": HoleReference(43, (15.0, 43.0), 1),
         "nose": HoleReference(10, (20.5, 31.5), 1)},
        ear_gap_rows=5,
    )
    report = run_regression(generate, cat_references={1: reference})
    assert report.matrix_passed, [
        (case.fixture, case.shape, case.issues, case.verification.diagnostics)
        for case in report.cases if case.issues
    ]
    assert report.comparisons == 144
    assert report.build_counts == {"object": 18, "original": 6, "rendered": 18}
    assert len(roots) == 1 and all(not root.exists() for root in roots)
    assert report.cat_scales[1].status == CheckStatus.PASS, report.cat_scales
    assert report.cat_scales[2].status == CheckStatus.NOT_RUN
    assert report.cat_scales[4].status == CheckStatus.NOT_RUN
    assert not report.passed


def test_regression_reports_unverified_cases_and_cancellation():
    event = Event()

    def generate(selection, shape, *, ctx):
        assert selection.fixture is BUILTIN_FIXTURES["max2"]
        assert shape.kind == "circle"
        assert ctx.cancel_event is event
        event.set()
        return None

    report = run_regression(generate, ctx=context(event=event))
    assert len(report.cases) == 1
    assert report.cases[0].issues == ("VERIFICATION_MISSING",)
    assert report.interrupted == "CANCELLED"
    assert not report.matrix_passed
