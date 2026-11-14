"""CLI sample eligibility and source/report output through the normal entry point."""

import json
import os
import subprocess
import sys

import pytest

from codeart.presentation import describe_result
from codeart.contracts import CheckStatus, Diagnostic, ErrorCode, GenerationResult, VerificationReport
from fixtures.verification_reports import make_verifier_stub


def test_cli_real_sample_source_and_report(tmp_path):
    output = tmp_path / "max2.c"
    report_path = tmp_path / "max2.json"
    command = [
        sys.executable, "-m", "codeart.cli", "--sample", "max2", "--shape", "cat",
        "--scale", "1.5", "--output", str(output), "--report", str(report_path),
    ]
    # macOS occasionally needs more than the plan's 2 s behavior batch budget
    # for the first execution of a freshly linked binary. Retry only that
    # pre-existing flake, at most twice; the product budget and checks are unchanged.
    for _ in range(3):
        result = subprocess.run(command, capture_output=True, text=True, timeout=35)
        if result.returncode == 0 or "EXECUTION_TIMEOUT" not in result.stderr:
            break
    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text())
    assert report["verified"]
    assert all(item["status"] == "PASS" for item in report["checks"].values())
    assert report["layout"]["scale"] == 1.5
    assert output.read_bytes() == report["source_text"].encode()
    assert output.read_bytes().endswith(b"\n")


def test_cli_skipped_required_check_returns_nonzero(monkeypatch):
    import codeart.cli as cli
    result = GenerationResult(verification=VerificationReport(
        token_status=CheckStatus.PASS,
        geometry_status=CheckStatus.PASS,
        compile_status=CheckStatus.NOT_RUN,
    ))
    monkeypatch.setattr(cli, "generate", lambda *args, **kwargs: result)
    assert cli.main(["--sample", "max2"]) == 1


@pytest.mark.parametrize(("option", "alias"), [
    ("--source", "direct"), ("--source", "symlink"),
    ("--output", "direct"), ("--output", "hardlink"),
])
def test_cli_rejects_report_paths_that_alias_source_files(tmp_path, option, alias):
    source_file = tmp_path / "case.c"
    original = b"int f(void) { return __LINE__; }\n"
    source_file.write_bytes(original)
    report = source_file
    if alias == "symlink":
        report = tmp_path / "report.json"
        report.symlink_to(source_file)
    elif alias == "hardlink":
        report = tmp_path / "report.json"
        os.link(source_file, report)
    arguments = [] if option == "--source" else ["--sample", "max2"]

    result = subprocess.run(
        [sys.executable, "-m", "codeart.cli", *arguments,
         option, str(source_file), "--report", str(report)],
        capture_output=True, text=True, timeout=35,
    )

    assert result.returncode == 2
    assert f"--report and {option} must refer to different files" in result.stderr
    assert source_file.read_bytes() == original
    assert report.read_bytes() == original


def test_failed_layout_keeps_attempt_history():
    history = [{"scale": 2, "reason": "capacity exhausted"}]
    result = GenerationResult(diagnostics=[
        Diagnostic(ErrorCode.LAYOUT_LIMIT, "layout", "No room", details={"attempt_history": history})
    ])
    report = describe_result(result)
    assert not report["verified"]
    assert report["attempt_history"] == history
    assert report["source_text"] is None
    assert report["checks"]["geometry"]["status"] == "NOT_RUN"


@pytest.mark.parametrize("option", ["--source", "--file"])
@pytest.mark.parametrize("alias", ["direct", "symlink", "hardlink"])
def test_cli_rejects_output_paths_that_alias_input(tmp_path, option, alias):
    source_file = tmp_path / "input.c"
    original = b"int f(void){return 0;}\n"
    source_file.write_bytes(original)
    output = source_file
    if alias == "symlink":
        output = tmp_path / "output.c"
        output.symlink_to(source_file)
    elif alias == "hardlink":
        output = tmp_path / "output.c"
        os.link(source_file, output)

    result = subprocess.run(
        [sys.executable, "-m", "codeart.cli", option, str(source_file),
         "--output", str(output)],
        capture_output=True, text=True, timeout=35,
    )

    assert result.returncode == 2
    assert f"{option} and --output must refer to different files" in result.stderr
    assert source_file.read_bytes() == original
    assert output.read_bytes() == original


def test_cli_prepass_timeout_keeps_common_failure_report(tmp_path, monkeypatch):
    import codeart.cli as cli
    from codeart.contracts import StageError

    def stopped(*args, **kwargs):
        raise StageError(Diagnostic(ErrorCode.PIPELINE_TIMEOUT, "pipeline", "Timed out"))

    source = tmp_path / "input.c"
    source.write_text("int f(void){return 0;}\n")
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(cli, "inspect_file", stopped)

    assert cli.main(["--file", str(source), "--report", str(report_path)]) == 1
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAILED"
    assert report["prepass"]["error"] == "PIPELINE_TIMEOUT"
    assert report["diagnostics"][0]["code"] == "PIPELINE_TIMEOUT"
    assert all(check["status"] == "NOT_RUN" for check in report["checks"].values())


def test_artifact_names_include_realized_size():
    from codeart.presentation import artifact_name
    fixed = artifact_name("max2", "cat", {"height": 32, "scale": 1})
    grown = artifact_name("max2", "cat", {"height": 64, "scale": 2})
    assert fixed == "case_max2_cat_h32_s1.c"
    assert grown == "case_max2_cat_h64_s2.c"
    assert fixed != grown


@pytest.mark.parametrize(("case", "status", "verified"), [
    ("pass", "OK", True),
    ("token_mismatch", "FAILED", False),
    ("hole_leakage", "FAILED", False),
    ("compiler_unavailable", "FAILED", False),
])
def test_cli_report_uses_e_verifier_stub(tmp_path, monkeypatch, case, status, verified):
    import codeart.cli as cli
    report = make_verifier_stub(case)(None, None, None, None, None, ctx=None)
    result = GenerationResult(verification=report)
    monkeypatch.setattr(cli, "generate", lambda *args, **kwargs: result)
    path = tmp_path / "report.json"

    assert cli.main(["--sample", "max2", "--report", str(path)]) == (0 if status == "OK" else 1)
    data = json.loads(path.read_text())
    assert data["status"] == status
    assert data["verified"] is verified
    assert {name: data["checks"][name]["status"] for name in ("token", "geometry", "compile", "behavior")} == {
        name: getattr(report, f"{name}_status").value
        for name in ("token", "geometry", "compile", "behavior")
    }
