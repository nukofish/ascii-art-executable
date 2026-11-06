"""Command-line entry point for the integration smoke demo and production pipeline."""

import argparse
from pathlib import Path
import sys

from ._integration_demo import CHECKS, DEMO_SOURCE, demo_deps
from .contracts import CheckStatus, GenerationRequest, ShapeSpec
from .pipeline import generate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--demo", action="store_true", help="use the fixed smoke fixture")
    inputs.add_argument("--source", type=Path, help="path to a C11 function")
    parser.add_argument("--shape", choices=("circle", "cat", "code"), default="circle")
    parser.add_argument("--output", type=Path, help="write generated source to this file")
    args = parser.parse_args(argv)

    try:
        source = DEMO_SOURCE if args.demo else args.source.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        parser.exit(2, f"Cannot read source: {exc}\n")

    if args.demo:
        print("Integration demo: real B mask, simulated A/C/D/E. Checks are not run.", file=sys.stderr)
    result = generate(
        GenerationRequest(source, ShapeSpec(args.shape, "CODE" if args.shape == "code" else None)),
        deps=demo_deps() if args.demo else None,
    )

    if result.plan is not None:
        plan = result.plan
        print(f"{plan.mask.width} x {plan.mask.height}; scale={plan.actual_scale:g}; "
              f"attempts={plan.attempt_count}", file=sys.stderr)
    if result.rendered is not None:
        print(f"coverage={result.rendered.coverage:.2%}", file=sys.stderr)
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
    if report is None:
        return 1
    required = (report.token_status, report.geometry_status, report.compile_status)
    return int(bool(result.diagnostics) or any(status != CheckStatus.PASS for status in required)
               or report.behavior_status == CheckStatus.FAIL)


if __name__ == "__main__":
    raise SystemExit(main())
