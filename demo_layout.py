"""Zero-input demo for the real Part C layout engine.

Run with ``python demo_layout.py``.  It uses only the fixed fixture source
(no external files or images), drives the real :func:`codeart.layout.fit_layout`
and Part D renderer, and prints:

  STEP 1 - the original C source, in normal layout;
  STEP 2 - the same real tokens arranged as a cat shape;
  STEP 3 - the geometry verification verdict.
"""

from __future__ import annotations

import sys
from time import monotonic

from codeart import ShapeSpec, build_mask
from codeart._verification_geometry import check_geometry
from codeart.contracts import (
    FillOptions, LayoutOptions, RunContext, SourceModel, Token, VerificationProfile)
from codeart.fill import render_source
from codeart.layout import fit_layout

# Fixed single-function C fixture.
SOURCE = "int identity(int n){return n;}"
RAW_TOKENS = (
    ("keyword", "int"), ("identifier", "identity"), ("punctuator", "("),
    ("keyword", "int"), ("identifier", "n"), ("punctuator", ")"),
    ("punctuator", "{"), ("keyword", "return"), ("identifier", "n"),
    ("punctuator", ";"), ("punctuator", "}"),
)


def _can_join(run, nxt, profile):
    """Realistic C rule: two words need a space; punctuation can join."""
    if not run:
        return True
    prev = run[-1]
    return not (
        prev.kind in ("identifier", "keyword")
        and nxt.kind in ("identifier", "keyword"))


def main() -> int:
    tokens = tuple(
        Token(i, kind, spelling, len(spelling), 1, i + 1)
        for i, (kind, spelling) in enumerate(RAW_TOKENS))
    model = SourceModel(SOURCE, SOURCE, tokens, VerificationProfile(),
                        "identity", "int identity(int n)")
    ctx = RunContext(monotonic() + 30)
    options = LayoutOptions()

    plan = fit_layout(model, ShapeSpec("cat"), options,
                      mask_builder=build_mask, join_checker=_can_join, ctx=ctx)
    rendered = render_source(model, plan, FillOptions(), ctx=ctx)
    _, issues = check_geometry(model, plan, rendered, None, ctx)

    print("=" * 70)
    print("STEP 1 - Original C source (normal layout)")
    print("=" * 70)
    print(SOURCE)
    print()
    print("=" * 70)
    print("STEP 2 - The same real tokens arranged as a cat shape")
    print("=" * 70)
    print(rendered.source_text)
    print("=" * 70)
    print("STEP 3 - Geometry verification")
    print("=" * 70)
    print(f"mask: {plan.mask.width} x {plan.mask.height}; "
          f"placements: {len(plan.placements)}; attempts: {plan.attempt_count}")
    print(f"coverage: {rendered.coverage:.2%}")
    if issues.reasons:
        print("RESULT: FAIL -", ", ".join(issues.reasons))
        return 1
    print("RESULT: PASS - every token is placed on the mask without overlap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
