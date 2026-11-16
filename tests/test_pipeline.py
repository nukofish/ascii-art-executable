from dataclasses import replace
from threading import Event

import pytest

from codeart import pipeline
from codeart._integration_demo import DEMO_SOURCE, demo_deps
from codeart.contracts import (
    CheckStatus, Diagnostic, ErrorCode, GenerationRequest, GenerationResult,
    GenerationStatus, ShapeSpec, StageError, VerificationReport,
)
from codeart.presentation import describe_result
from fixtures.verification_reports import make_verifier_stub


@pytest.fixture
def request_data():
    return GenerationRequest(DEMO_SOURCE, ShapeSpec("circle"))


def test_deps_are_explicit_and_share_one_context(request_data):
    deps = demo_deps()
    contexts = []

    def analyze(text, profile, *, ctx):
        contexts.append(ctx)
        return deps.analyzer(text, profile, ctx=ctx)

    def mask(*args, ctx):
        contexts.append(ctx)
        return deps.mask_builder(*args, ctx=ctx)

    def join(run_tokens, next_token, profile):
        return True

    def layout(model, shape_spec, options, *, mask_builder, join_checker, ctx):
        contexts.append(ctx)
        assert mask_builder is mask
        assert join_checker is join
        return deps.layout_engine(model, shape_spec, options, mask_builder=mask_builder,
                                  join_checker=join_checker, ctx=ctx)

    def render(*args, ctx):
        contexts.append(ctx)
        return deps.renderer(*args, ctx=ctx)

    report = VerificationReport(geometry_status=CheckStatus.FAIL)

    def verify(*args, ctx):
        contexts.append(ctx)
        return report

    result = pipeline.generate(request_data, deps=replace(
        deps, analyzer=analyze, mask_builder=mask, join_checker=join,
        layout_engine=layout, renderer=render, verifier=verify,
    ))
    assert result.verification is report
    assert result.status == GenerationStatus.FAILED
    assert result.rendered.source_text.endswith("\n")
    assert len(contexts) == 5
    assert all(ctx is contexts[0] for ctx in contexts)


def test_diagnosed_layout_failure_stops_pipeline(request_data):
    diagnostic = Diagnostic(ErrorCode.LAYOUT_LIMIT, "layout", "test layout limit")

    def layout(*args, **kwargs):
        raise StageError(diagnostic)

    result = pipeline.generate(request_data, deps=replace(demo_deps(), layout_engine=layout))
    assert result.diagnostics == [diagnostic]
    assert result.status == GenerationStatus.FAILED
    assert result.plan is result.rendered is result.verification is None


def test_cancelled_mask_stops_work(request_data):
    event = Event()

    def mask(*args, ctx):
        event.set()
        return demo_deps().mask_builder(*args, ctx=ctx)

    result = pipeline.generate(request_data, deps=replace(demo_deps(), mask_builder=mask),
                               cancel_event=event)
    assert result.plan is None
    assert result.status == GenerationStatus.CANCELLED
    assert [d.code for d in result.diagnostics] == [ErrorCode.CANCELLED]


def test_cancel_after_render_preserves_output(request_data):
    event = Event()
    deps = demo_deps()

    def render(*args, ctx):
        result = deps.renderer(*args, ctx=ctx)
        event.set()
        return result

    result = pipeline.generate(request_data, deps=replace(deps, renderer=render), cancel_event=event)
    assert result.plan is not None
    assert result.rendered is not None
    assert result.verification is None
    assert result.status == GenerationStatus.CANCELLED
    assert [d.code for d in result.diagnostics] == [ErrorCode.CANCELLED]


def test_expired_budget_prevents_next_stage(request_data, monkeypatch):
    times = iter((10.0, 10.0, 10.0, 40.0))
    monkeypatch.setattr(pipeline, "monotonic", lambda: next(times))
    context_type = pipeline.RunContext
    monkeypatch.setattr(pipeline, "RunContext", lambda deadline, event: context_type(
        deadline, event, clock=pipeline.monotonic,
    ))
    result = pipeline.generate(request_data, deps=demo_deps())
    assert result.plan is result.rendered is result.verification is None
    assert result.status == GenerationStatus.FAILED
    assert [d.code for d in result.diagnostics] == [ErrorCode.PIPELINE_TIMEOUT]


def test_production_reports_a_missing_module(request_data, monkeypatch):
    def unavailable(name):
        raise ModuleNotFoundError(name, name=name)

    monkeypatch.setattr(pipeline, "import_module", unavailable)
    result = pipeline.generate(request_data)
    assert result.status == GenerationStatus.FAILED
    assert [d.code for d in result.diagnostics] == [ErrorCode.DEPENDENCY_UNAVAILABLE]
    assert "codeart.source" in result.diagnostics[0].message


def test_skipped_required_check_sets_failed_status(request_data):
    report = VerificationReport(
        token_status=CheckStatus.PASS,
        geometry_status=CheckStatus.PASS,
        compile_status=CheckStatus.NOT_RUN,
    )
    result = pipeline.generate(
        request_data, deps=replace(demo_deps(), verifier=lambda *a, **k: report))
    assert result.status == GenerationStatus.FAILED
    assert describe_result(result)["verified"] is False


def test_old_positional_generation_result_constructor_still_works():
    diagnostic = Diagnostic(ErrorCode.LAYOUT_LIMIT, "layout", "old positional")
    result = GenerationResult(None, None, None, [diagnostic])
    assert result.plan is None
    assert result.rendered is None
    assert result.verification is None
    assert result.diagnostics == [diagnostic]
    assert result.status == GenerationStatus.FAILED


@pytest.mark.parametrize("status", [GenerationStatus.FAILED, GenerationStatus.CANCELLED])
def test_failed_or_cancelled_result_is_not_verified(status):
    report = VerificationReport(
        token_status=CheckStatus.PASS,
        geometry_status=CheckStatus.PASS,
        compile_status=CheckStatus.PASS,
        behavior_status=CheckStatus.PASS,
    )
    summary = describe_result(GenerationResult(verification=report, status=status))

    assert summary["status"] == status.value
    assert summary["verified"] is False


@pytest.mark.parametrize(("case", "checks", "status"), [
    ("pass", {"token": "PASS", "geometry": "PASS", "compile": "PASS", "behavior": "PASS"}, "OK"),
    ("token_mismatch", {"token": "FAIL", "geometry": "NOT_RUN", "compile": "NOT_RUN", "behavior": "NOT_RUN"}, "FAILED"),
    ("hole_leakage", {"token": "PASS", "geometry": "FAIL", "compile": "PASS", "behavior": "NOT_RUN"}, "FAILED"),
    ("compiler_unavailable", {"token": "PASS", "geometry": "PASS", "compile": "NOT_RUN", "behavior": "NOT_RUN"}, "FAILED"),
    ("wrapper_compile_failure", {"token": "PASS", "geometry": "PASS", "compile": "FAIL", "behavior": "NOT_RUN"}, "FAILED"),
])
def test_e_verifier_stubs_flow_through_f(request_data, case, checks, status):
    result = pipeline.generate(
        request_data, deps=replace(demo_deps(), verifier=make_verifier_stub(case)))
    summary = describe_result(result)
    assert summary["status"] == status
    assert {name: summary["checks"][name]["status"] for name in checks} == checks
    assert summary["verified"] is (status == "OK")
