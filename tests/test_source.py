"""Source analysis, shared contracts, isolation and real pipeline regression."""

import os
import sys
from threading import Event, Timer
from time import monotonic

import pytest

from codeart import source
from codeart.contracts import (
    ErrorCode, GenerationRequest, RunContext, ShapeSpec, SourceModel,
    StageError, Token, VerificationProfile,
)
from codeart.pipeline import generate
from codeart.verification_fixtures import BUILTIN_FIXTURES, select_builtin

SIMPLE = "int f(void) { return 0; }"


def test_shared_contracts_and_missing_final_newline():
    model = source.analyze_source(SIMPLE)
    assert isinstance(model, SourceModel)
    assert isinstance(model.tokens[0], Token)
    assert model.original_source == SIMPLE
    assert model.normalized_source == SIMPLE
    assert model.function_name == "f"
    assert model.profile.lex_source is not None


def test_source_analysis_uses_injected_clock_for_child_processes():
    model = source.analyze_source(SIMPLE, ctx=RunContext(10.0, clock=lambda: 0.0))
    assert model.function_name == "f"


@pytest.mark.parametrize("text", [
    "int f(int x) { return g(x); }",
    "int f(void) { return ext; }",
    "int f(void) { extern int g(void); return g(); }",
    "int f(void) { extern int x; return x; }",
    "int x; int f(void) { return x; }",
    "int g(void); int f(void) { return g(); }",
    "int f(void) { return __LINE__; }",
    "int f(void) { return __INT_MAX__; }",
    "int f(void) { return __TIMESTAMP__[0]; }",
    "int f(void) { return \"a\tb\"[1]; }",
    "int f(void) { ret\\\nurn 0; }",
    "int f(void) { /* 中文 */ return 0; }",
    "#define VALUE 0\nint f(void) { return VALUE; }",
])
def test_reject_unsupported_source(text):
    with pytest.raises(StageError) as exc:
        source.analyze_source(text)
    assert exc.value.diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert exc.value.diagnostic.line is not None


def test_reject_invalid_syntax():
    with pytest.raises(StageError) as exc:
        source.analyze_source("int f(void) { return ;;; ??? }")
    assert exc.value.diagnostic.code == ErrorCode.INVALID_SOURCE


def test_comments_literals_and_crlf():
    text = '/*\r\n# comment only\r\n*/\r\nint f(int i){return "__LINE__ /* #" [i];}\r\n'
    model = source.analyze_source(text)
    assert model.original_source == text
    assert "\r" not in model.normalized_source
    assert len(model.original_comments) == 1
    assert model.tokens[0].source_line == 4
    assert any(token.spelling == '"__LINE__ /* #"' for token in model.tokens)


def test_recursion_and_escaped_tab_are_supported():
    model = source.analyze_source("int gcd(int a,int b){return b==0?a:gcd(b,a%b);}")
    assert model.function_name == "gcd"
    model = source.analyze_source('int f(int i){return "a\\tb"[i];}')
    assert any(token.spelling == '"a\\tb"' for token in model.tokens)


@pytest.mark.parametrize("run,next_token,expected", [
    ([("IDENTIFIER", "f")], ("PUNCTUATION", "("), True),
    ([("IDENTIFIER", "i")], ("PUNCTUATION", "++"), True),
    ([("PUNCTUATION", "+")], ("PUNCTUATION", "+"), False),
    ([("PUNCTUATION", "/")], ("PUNCTUATION", "*"), False),
    ([("PUNCTUATION", "."), ("PUNCTUATION", ".")], ("PUNCTUATION", "."), False),
    ([("KEYWORD", "int")], ("IDENTIFIER", "a"), False),
    ([("IDENTIFIER", "a"), ("PUNCTUATION", "+"), ("IDENTIFIER", "b"),
      ("PUNCTUATION", "+"), ("IDENTIFIER", "c")], ("PUNCTUATION", ";"), True),
    ([("KEYWORD", "f")], ("PUNCTUATION", "("), False),
])
def test_full_run_kind_and_spelling_comparison(run, next_token, expected):
    tokens = [Token(i, kind, spelling, len(spelling), 1, 1)
              for i, (kind, spelling) in enumerate([*run, next_token])]
    assert source.can_join(tokens[:-1], tokens[-1], VerificationProfile()) is expected


def test_invalid_input_keeps_diagnostic_through_pipeline():
    result = generate(GenerationRequest("int f(void){return 变量;}", ShapeSpec("circle")))
    assert result.plan is None
    assert result.diagnostics[0].code == ErrorCode.UNSUPPORTED_SOURCE


@pytest.mark.parametrize(("clock", "budget", "cancel", "expected"), [
    (monotonic, 30, False, ErrorCode.ANALYSIS_TIMEOUT),
    (monotonic, 30, True, ErrorCode.CANCELLED),
    (lambda: 100.0, 30, False, ErrorCode.ANALYSIS_TIMEOUT),
    (lambda: 100.0, 0.35, False, ErrorCode.PIPELINE_TIMEOUT),
    (lambda: 100.0, 30, True, ErrorCode.CANCELLED),
])
def test_analysis_stops_and_reaps_worker(monkeypatch, tmp_path, clock, budget, cancel, expected):
    actual_run = source.run_command
    pid_file = tmp_path / "worker.pid"

    def slow_worker(args, **kwargs):
        script = (
            "import os,time; from pathlib import Path; "
            f"Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(1)"
        )
        return actual_run([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(source, "run_command", slow_worker)
    event = Event()
    timer = Timer(0.25, event.set)
    if cancel:
        timer.start()
    try:
        with pytest.raises(StageError) as exc:
            source.analyze_source(SIMPLE, VerificationProfile(lex_timeout=0.5),
                                  ctx=RunContext(clock() + budget, event, clock=clock))
    finally:
        timer.cancel()
    assert exc.value.diagnostic.code == expected
    assert pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


@pytest.mark.parametrize("name", tuple(BUILTIN_FIXTURES))
@pytest.mark.parametrize("shape", ("circle", "cat", "code"))
def test_real_pipeline_builtin_matrix(name, shape):
    selection = select_builtin(name)
    request = GenerationRequest(selection.fixture.source, ShapeSpec(shape), fixtures=selection)
    result = generate(request)
    assert not result.diagnostics, result.diagnostics
    report = result.verification
    assert report is not None
    assert tuple(getattr(report, f"{stage}_status").value
                 for stage in ("token", "geometry", "compile", "behavior")) == ("PASS",) * 4
    assert report.behavior_cases_compared == 8


@pytest.mark.parametrize("text", [
    "int f(int x){return g(x);}",
    "int f(void){return ext;}",
])
def test_external_diagnostics_use_stable_codes(text):
    # AST and compiler diagnostics may have different human-readable wording.
    with pytest.raises(StageError) as exc:
        source.analyze_source(text)
    diagnostic = exc.value.diagnostic
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert diagnostic.stage == "analysis"
    assert diagnostic.line == 1
    assert diagnostic.column > 0


@pytest.mark.parametrize("text", [
    "int f(void) { static int c=0; return ++c; }",
    "int f(void) { static const int c=1; return c; }",
    "int main(void) { return (int)sizeof(__func__); }",
])
def test_standard_local_declarations_and_function_name_survive_generation(text):
    result = generate(GenerationRequest(text, ShapeSpec("circle")))
    assert not result.diagnostics, result.diagnostics
    report = result.verification
    assert (report.token_status.value, report.geometry_status.value,
            report.compile_status.value, report.behavior_status.value) == (
                "PASS", "PASS", "PASS", "NOT_RUN",
            )
