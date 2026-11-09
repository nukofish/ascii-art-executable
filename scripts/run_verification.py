"""Run Part E's fixed-size acceptance matrix and write its evidence."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import platform
from subprocess import CalledProcessError, check_output
from time import monotonic

from codeart.contracts import GenerationRequest, LayoutOptions, VerificationReport
from codeart.pipeline import generate
from codeart.procutil import WorkStopped
from codeart.verification_regression import run_regression


ROOT = Path(__file__).resolve().parents[1]
HEIGHT = 32
CHECKS = ("token", "geometry", "compile", "behavior")


def _git_state():
    def git(*args):
        return check_output(["git", *args], cwd=ROOT, text=True).strip()

    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))


def _run_matrix(output_dir):
    options = LayoutOptions(base_height_rows=HEIGHT, max_attempts=1)
    results = []

    def generate_case(selection, shape, *, ctx):
        remaining = ctx.remaining_s()
        if remaining == 0:
            raise WorkStopped("PIPELINE_TIMEOUT")
        start = monotonic()
        result = generate(GenerationRequest(
            selection.fixture.source, shape, layout_options=options,
            fixtures=selection, timeout_s=remaining,
        ), cancel_event=ctx.cancel_event)
        results.append((result, monotonic() - start))
        return result.verification

    matrix = run_regression(generate_case)
    cases = []
    for case, (result, elapsed_s) in zip(matrix.cases, results, strict=True):
        mask = result.plan.mask if result.plan is not None else None
        issues = list(case.issues)
        filename = None
        if mask is not None and mask.height != HEIGHT:
            issues.append("WRONG_HEIGHT")
        if result.rendered is None:
            issues.append("OUTPUT_MISSING")
        elif mask is not None:
            filename = f"case_{case.fixture}_{case.shape}_h{mask.height}.c"
            (output_dir / filename).write_bytes(result.rendered.source_text.encode("utf-8"))
        else:
            issues.append("LAYOUT_MISSING")

        verification = case.verification or VerificationReport(
            skip_reasons=dict.fromkeys(CHECKS, "PIPELINE_STOPPED"),
        )
        cases.append({
            "fixture": case.fixture,
            "shape": case.shape,
            "height_rows": mask.height if mask is not None else None,
            "width_columns": mask.width if mask is not None else None,
            "source_file": filename,
            "elapsed_s": elapsed_s,
            "issues": issues,
            "verification": asdict(verification),
            "generation_diagnostics": [asdict(item) for item in result.diagnostics],
        })

    return {
        "fixed_matrix_passed": matrix.matrix_passed and all(not case["issues"] for case in cases),
        "behavior_comparisons": matrix.comparisons,
        "build_counts": matrix.build_counts,
        "elapsed_s": matrix.elapsed_s,
        "interrupted": matrix.interrupted,
        "cat_scales": {scale: asdict(result) for scale, result in matrix.cat_scales.items()},
        "cases": cases,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="new evidence directory")
    args = parser.parse_args(argv)
    try:
        commit, dirty = _git_state()
        args.output_dir.mkdir(parents=True, exist_ok=False)
    except (OSError, CalledProcessError) as exc:
        parser.error(str(exc))

    summary = {
        "schema_version": 1,
        "commit": commit,
        "checkout_dirty": dirty,
        "python": platform.python_version(),
        "height_rows": HEIGHT,
        **_run_matrix(args.output_dir),
    }
    report_path = args.output_dir / "report.json"
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    status = "PASS" if summary["fixed_matrix_passed"] else "FAIL"
    print(f"{status} fixed matrix ({summary['behavior_comparisons']}/144 comparisons) | {report_path}")
    return int(not summary["fixed_matrix_passed"])


if __name__ == "__main__":
    raise SystemExit(main())
