"""Command-line entry point for the integration smoke demo and production pipeline."""

import argparse
from dataclasses import replace
from itertools import combinations
import json
from pathlib import Path
import sys

from ._integration_demo import DEMO_SOURCE, demo_deps
from .contracts import (
    CheckStatus, FontMetrics, GenerationRequest, GenerationStatus, PipelineError, ShapeSpec,
)
from .environment import revision_info
from .pipeline import generate
from .prepass import inspect_file, selected_source, PrepassResult, SCOPE
from .presentation import json_value
from .presentation import CHECKS, FONT_ID, LOW_CODE_FILL_WARNING, describe_prepass_failure, describe_result
from .verification_fixtures import BUILTIN_FIXTURES, select_builtin


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--demo", action="store_true", help="use the fixed smoke fixture")
    inputs.add_argument("--sample", choices=tuple(BUILTIN_FIXTURES), help="verify a real built-in sample")
    inputs.add_argument("--source", type=Path, help="path to a C11 function")
    inputs.add_argument("--file", type=Path, help="extract a function from a complete C file")
    parser.add_argument("--function", help="exact function name for --file")
    parser.add_argument("--shape", choices=("circle", "cat", "code"), default="circle")
    parser.add_argument("--output", type=Path, help="write generated source to this file")
    parser.add_argument("--scale", type=float, default=1.0, help="initial scale, between 1 and 4")
    parser.add_argument("--report", type=Path, help="write a JSON run report")
    args = parser.parse_args(argv)
    if args.function and not args.file:
        parser.error("--function requires --file")
    if not 1 <= args.scale <= 4:
        parser.error("--scale must be between 1 and 4")
    paths = [(option, path) for option, path in (
        ("--report", args.report), ("--file", args.file),
        ("--source", args.source), ("--output", args.output),
    ) if path is not None]
    try:
        for (left_option, left), (right_option, right) in combinations(paths, 2):
            if left.resolve() == right.resolve() or (
                left.exists() and right.exists() and left.samefile(right)
            ):
                parser.error(f"{left_option} and {right_option} must refer to different files")
    except (OSError, RuntimeError) as exc:
        parser.exit(2, f"Cannot check file paths: {exc}\n")
    selection = select_builtin(args.sample) if args.sample else None

    try:
        source = DEMO_SOURCE if args.demo else selection.fixture.source if selection else (args.file or args.source).read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        parser.exit(2, f"Cannot read source: {exc}\n")

    prepass_diagnostics = []
    try:
        extraction = inspect_file(source, args.function) if args.file else None
    except PipelineError as exc:
        extraction = PrepassResult(error=exc.diagnostic.code.value)
        prepass_diagnostics.append(exc.diagnostic)
    if extraction:
        print(SCOPE, file=sys.stderr)
        if extraction.error:
            data = describe_prepass_failure(extraction)
            data["diagnostics"] = json_value(prepass_diagnostics)
            data["revision"] = revision_info()
            if args.report:
                try:
                    args.report.write_text(json.dumps(data, indent=2), encoding="utf-8")
                except OSError as exc:
                    parser.exit(2, f"Cannot write report: {exc}\n")
            print(json.dumps(data, indent=2), file=sys.stderr)
            return 1
        source = selected_source(extraction)

    if args.demo:
        print("Integration demo: real B mask, simulated A/C/D/E. Checks are not run.", file=sys.stderr)
    request = GenerationRequest(
        source, ShapeSpec(args.shape, "CODE" if args.shape == "code" else None), fixtures=selection,
    )
    request = replace(request, layout_options=replace(
        request.layout_options, initial_scale=args.scale,
        font_metrics=FontMetrics(font_id=FONT_ID),
    ))
    result = generate(request, deps=demo_deps() if args.demo else None)
    if args.report:
        try:
            report = describe_result(result)
            report["revision"] = revision_info()
            if extraction:
                report["prepass"] = json_value(extraction)
            args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as exc:
            parser.exit(2, f"Cannot write report: {exc}\n")

    if result.plan is not None:
        plan = result.plan
        print(f"{plan.mask.width} x {plan.mask.height}; scale={plan.actual_scale:g}; "
              f"attempts={plan.attempt_count}", file=sys.stderr)
    if result.rendered is not None:
        print(f"coverage={result.rendered.coverage:.2%}; code_fill_ratio={result.rendered.token_coverage:.2%}", file=sys.stderr)
    if result.rendered is not None and result.rendered.token_coverage < 0.10:
        print(LOW_CODE_FILL_WARNING, file=sys.stderr)
    report = result.verification
    for name in CHECKS:
        status = getattr(report, f"{name}_status", CheckStatus.NOT_RUN)
        reason = report.skip_reasons.get(name) if report is not None else "PIPELINE_STOPPED"
        print(f"{name}: {status.value}" + (f" ({reason})" if reason else ""), file=sys.stderr)
    for diagnostic in result.diagnostics:
        position = f":{diagnostic.line}" if diagnostic.line is not None else ""
        if diagnostic.column is not None:
            position += f":{diagnostic.column}"
        print(f"{diagnostic.stage}{position}: {diagnostic.code.value}: {diagnostic.message}",
              file=sys.stderr)

    if result.rendered is not None:
        data = result.rendered.source_text.encode("utf-8")
        try:
            if args.output is None:
                sys.stdout.buffer.write(data)
            else:
                args.output.write_bytes(data)
        except OSError as exc:
            parser.exit(2, f"Cannot write output: {exc}\n")

    if args.demo:
        return int(bool(result.diagnostics) or result.rendered is None)
    return int(result.status != GenerationStatus.OK)


if __name__ == "__main__":
    raise SystemExit(main())
