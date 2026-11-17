import json

import pytest

from codeart.contracts import AttemptRecord, Diagnostic, ErrorCode, GenerationResult
from codeart.verification_regression import load_cat_references, run_regression
from scripts import run_verification


def test_cat_references_use_h32_area_and_per_scale_geometry():
    references = load_cat_references(run_verification.SHAPE_FIXTURES)
    assert {
        scale: {name: hole.boundary_cells for name, hole in reference.holes.items()}
        for scale, reference in references.items()
    } == {
        1: {"eye_left": 31, "eye_right": 31, "nose": 14},
        2: {"eye_left": 63, "eye_right": 63, "nose": 30},
        4: {"eye_left": 125, "eye_right": 125, "nose": 62},
    }
    scale_four = references[4]
    eye = scale_four.holes["eye_left"]
    assert eye.base_area == references[1].holes["eye_left"].base_area == 43
    assert eye.center == pytest.approx((62.191, 85.216))
    assert scale_four.ear_gap_rows == 20


@pytest.mark.parametrize("legacy_reference", (False, True), ids=("missing", "legacy"))
def test_cat_scale_without_exact_reference_is_not_run(tmp_path, legacy_reference):
    # h96 must not substitute for a missing acceptance height.
    for height in (32, 96, 128):
        name = f"metrics_h{height}.json"
        (tmp_path / name).write_bytes((run_verification.SHAPE_FIXTURES / name).read_bytes())
    if legacy_reference:
        name = "metrics_h64.json"
        document = json.loads((run_verification.SHAPE_FIXTURES / name).read_text())
        del document["shapes"]["cat"]["features"]["nose"]["boundary_cells"]
        (tmp_path / name).write_text(json.dumps(document))

    references = load_cat_references(tmp_path)
    assert set(references) == {1, 4}
    report = run_regression(lambda selection, shape, *, ctx: None, cat_references=references)
    assert report.cat_scales[2].status == "NOT_RUN"
    assert report.cat_scales[2].issues == ("MISSING_REFERENCE",)
    assert report.cat_scales[4].status == "PASS"


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
    assert not report["passed"]
    assert report["cat_scales"] == {
        scale: {"status": "PASS", "issues": []} for scale in ("1", "2", "4")
    }
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
