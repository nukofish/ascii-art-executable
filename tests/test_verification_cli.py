import json

import pytest

from codeart.contracts import AttemptRecord, Diagnostic, ErrorCode, GenerationResult
from scripts import run_verification


def test_fixed_matrix_archives_pipeline_failures_without_overwriting(tmp_path, monkeypatch):
    attempt = AttemptRecord(1.0, 64, 32, 0, "token did not fit", 0.1)

    def fail_layout(request, *, cancel_event):
        assert request.layout_options.base_height_rows == 32
        assert request.layout_options.max_attempts == 1
        assert request.source_text == request.fixtures.fixture.source
        return GenerationResult(diagnostics=[
            Diagnostic(ErrorCode.LAYOUT_LIMIT, "layout", "Token did not fit",
                       details={"attempt_history": (attempt,)}),
        ])

    monkeypatch.setattr(run_verification, "generate", fail_layout)
    monkeypatch.setattr(run_verification, "_git_state", lambda: ("example-sha", False))

    output = tmp_path / "fixed"
    args = ["--output-dir", str(output)]
    assert run_verification.main(args) == 1
    report_path = output / "report.json"
    saved = report_path.read_bytes()
    report = json.loads(saved)
    assert not report["fixed_matrix_passed"]
    assert report["commit"] == "example-sha"
    assert report["behavior_comparisons"] == 0
    assert len(report["cases"]) == 18
    assert not list(output.glob("*.c"))
    for case in report["cases"]:
        assert case["issues"] == ["VERIFICATION_MISSING", "OUTPUT_MISSING"]
        assert case["generation_diagnostics"][0]["details"]["attempt_history"][0]["height"] == 32
        for check in run_verification.CHECKS:
            assert case["verification"][f"{check}_status"] == "NOT_RUN"
            assert case["verification"]["skip_reasons"][check] == "PIPELINE_STOPPED"

    with pytest.raises(SystemExit) as exc:
        run_verification.main(args)
    assert exc.value.code == 2
    assert report_path.read_bytes() == saved
