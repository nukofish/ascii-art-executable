"""A fixed smoke fixture for F's CLI while A, C, D and E are being integrated."""

from time import monotonic

from .contracts import (
    AttemptRecord, Diagnostic, ErrorCode, LayoutPlan, PipelineDeps, Placement,
    RenderedCode, SizeRequest, SourceModel, StageError, Token, VerificationReport,
)
from .shapes import build_mask

DEMO_SOURCE = "int identity(int n){return n;}\n"
DEMO_TOKENS = (
    ("keyword", "int", 0), ("identifier", "identity", 4),
    ("punctuator", "(", 12), ("keyword", "int", 13),
    ("identifier", "n", 17), ("punctuator", ")", 18),
    ("punctuator", "{", 19), ("keyword", "return", 20),
    ("identifier", "n", 27), ("punctuator", ";", 28), ("punctuator", "}", 29),
)
CHECKS = ("token", "geometry", "compile", "behavior")


def demo_deps() -> PipelineDeps:
    def analyze(text, profile, *, ctx):
        if text != DEMO_SOURCE:
            raise StageError(Diagnostic(
                ErrorCode.UNSUPPORTED_SOURCE, "analysis", "The smoke demo accepts only its fixed fixture"
            ))
        tokens = tuple(Token(i, kind, spelling, len(spelling), 1, col + 1)
                       for i, (kind, spelling, col) in enumerate(DEMO_TOKENS))
        return SourceModel(text, text, tokens, profile, "identity", "int identity(int n)")

    def layout(model, shape_spec, options, *, mask_builder, join_checker, ctx):
        start_time = monotonic()
        mask = mask_builder(shape_spec, SizeRequest(options.base_height_rows), options.font_metrics, ctx=ctx)
        row, start, end = max(
            ((row, start, end) for row, spans in enumerate(mask.spans) for start, end in spans),
            key=lambda span: span[2] - span[1],
        )
        if end - start < len(DEMO_SOURCE.rstrip("\n")):
            raise StageError(Diagnostic(ErrorCode.LAYOUT_LIMIT, "layout", "Smoke fixture does not fit"))
        placements = tuple(Placement(token.index, row, start + token.source_column - 1)
                           for token in model.tokens)
        attempt = AttemptRecord(1.0, mask.width, mask.height, None, None, monotonic() - start_time)
        return LayoutPlan(mask, placements, frozenset(), 1.0, 1, (attempt,))

    def render(model, plan, fill_options, *, ctx):
        lines = [""] * plan.mask.height
        first = plan.placements[0]
        lines[first.row] = " " * first.col + model.normalized_source.rstrip("\n")
        positions = {item.token_index: (item.row, item.col) for item in plan.placements}
        coverage = sum(token.width for token in model.tokens) / sum(map(sum, plan.mask.allowed))
        return RenderedCode("\n".join(lines) + "\n", positions, coverage, coverage,
                            0.0, {"block": 0, "line": 0})

    def verify(model, plan, rendered, fixtures, profile, *, ctx):
        return VerificationReport(skip_reasons=dict.fromkeys(CHECKS, "DEMO_ONLY"))

    def join_checker(run_tokens, next_token, profile):
        return False

    return PipelineDeps(analyze, build_mask, join_checker, layout, render, verify)
