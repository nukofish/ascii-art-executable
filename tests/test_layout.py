"""Part C tests: token placement, protected blanks, bounded retries and errors."""

from __future__ import annotations

from time import monotonic

import pytest

from codeart import FontMetrics, ShapeSpec, build_mask
from codeart._verification_geometry import check_geometry
from codeart.contracts import (
    Diagnostic,
    ErrorCode,
    FillOptions,
    LayoutOptions,
    RunContext,
    SourceModel,
    StageError,
    Token,
    VerificationProfile,
)
from codeart.fill import render_source
from codeart.layout import fit_layout


def context(seconds=30):
    return RunContext(monotonic() + seconds)


def make_tokens(items):
    """Build Token objects from ``(kind, spelling)`` pairs."""
    return tuple(
        Token(index, kind, spelling, len(spelling), 1, index + 1)
        for index, (kind, spelling) in enumerate(items))


def model_for(tokens, name="f", signature="int f("):
    return SourceModel("src", "src", tuple(tokens), VerificationProfile(), name, signature)


def always_join(run, nxt, profile):
    return True


def never_join(run, nxt, profile):
    return False


# A small realistic C-like token set.
TOKEN_ITEMS = [
    ("keyword", "int"), ("identifier", "f"), ("punctuator", "("),
    ("punctuator", ")"), ("punctuator", "{"), ("keyword", "return"),
    ("identifier", "n"), ("punctuator", ";"), ("punctuator", "}"),
]


# ------------------------------------------------------------- basic placement


@pytest.mark.parametrize("kind", ("circle", "cat", "code"))
def test_one_placement_per_token_on_each_shape(kind):
    model = model_for(make_tokens(TOKEN_ITEMS))
    plan = fit_layout(model, ShapeSpec(kind), LayoutOptions(),
                      mask_builder=build_mask, join_checker=always_join, ctx=context())

    assert len(plan.placements) == len(model.tokens)
    assert [p.token_index for p in plan.placements] == [t.index for t in model.tokens]
    assert plan.attempt_count == 1
    assert plan.actual_scale == 1.0


def test_placements_stay_inside_mask_and_do_not_overlap():
    model = model_for(make_tokens(TOKEN_ITEMS))
    plan = fit_layout(model, ShapeSpec("cat"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=always_join, ctx=context())
    mask = plan.mask
    occupied = set()

    for token, placement in zip(model.tokens, plan.placements):
        row, col = placement.row, placement.col
        assert 0 <= row < mask.height
        assert 0 <= col < col + token.width <= mask.width
        assert all(mask.allowed[row][col:col + token.width])
        cells = {(row, col + off) for off in range(token.width)}
        assert not (cells & occupied)
        occupied |= cells


def test_placements_are_strictly_ordered():
    model = model_for(make_tokens(TOKEN_ITEMS))
    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=always_join, ctx=context())
    previous = None
    for placement in plan.placements:
        cell = (placement.row, placement.col)
        if previous is not None:
            assert cell > previous
        previous = cell


# ------------------------------------------------------------- protected blanks


def _used_span_count(mask, placements):
    """Count the distinct spans that the placements occupy."""
    used = set()
    for placement in placements:
        span_index = 0
        for row in range(mask.height):
            for start, end in mask.spans[row]:
                if row == placement.row and start <= placement.col < end:
                    used.add(span_index)
                span_index += 1
    return len(used)


def test_never_join_records_a_protected_blank_within_each_run():
    model = model_for(make_tokens(TOKEN_ITEMS))
    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=never_join, ctx=context())

    # A gap is needed only between consecutive tokens sharing a run. The first
    # token of every occupied span starts a fresh run, so the expected number
    # of gaps is token count minus the number of spans actually used.
    runs = _used_span_count(plan.mask, plan.placements)
    assert len(plan.protected_blanks) == len(model.tokens) - runs
    for row, col in plan.protected_blanks:
        assert plan.mask.allowed[row][col]


def test_always_join_keeps_tokens_adjacent_without_protected_blanks():
    model = model_for(make_tokens(TOKEN_ITEMS))
    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=always_join, ctx=context())
    assert plan.protected_blanks == frozenset()


def test_protected_blank_separates_two_adjacent_identifiers():
    tokens = make_tokens([("identifier", "aa"), ("identifier", "bb")])
    model = model_for(tokens)
    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=never_join, ctx=context())

    first, second = plan.placements
    assert first.row == second.row
    gap_cell = (first.row, first.col + tokens[0].width)
    assert gap_cell in plan.protected_blanks
    assert second.col == first.col + tokens[0].width + 1


# ------------------------------------------------------------- bounded retries


def test_growth_retries_until_the_tokens_fit():
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(60))
    model = model_for(tokens)
    options = LayoutOptions(base_height_rows=6, max_columns=800, max_rows=600)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=build_mask, join_checker=never_join, ctx=context())

    assert plan.attempt_count > 1
    assert len(plan.attempt_history) == plan.attempt_count
    # Failed attempts point at the token that could not be placed.
    failed = plan.attempt_history[:-1]
    assert all(record.failure_token_index is not None for record in failed)
    assert all(record.reason for record in failed)
    # The final record is the successful one.
    last = plan.attempt_history[-1]
    assert last.failure_token_index is None and last.reason is None
    # Consecutive attempts grow by the configured factor.
    scales = [record.scale for record in plan.attempt_history]
    assert scales == [pytest.approx(1.25 ** i) for i in range(len(scales))]


def test_exhausted_attempts_raise_layout_limit_with_history():
    # A single very wide token cannot fit any span of the small masks.
    wide = Token(0, "identifier", "w" * 100, 100, 1, 1)
    model = model_for((wide,))
    options = LayoutOptions(base_height_rows=4, max_attempts=3,
                            max_columns=800, max_rows=600)

    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=always_join, ctx=context())

    diagnostic: Diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_LIMIT
    assert diagnostic.stage == "layout"
    history = diagnostic.details["attempt_history"]
    assert len(history) == 3


def test_canvas_size_limit_raises_layout_limit():
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(200))
    model = model_for(tokens)
    # Growth quickly exceeds the small column limit.
    options = LayoutOptions(base_height_rows=4, max_attempts=5,
                            max_columns=10, max_rows=600)

    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=always_join, ctx=context())

    diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_LIMIT
    assert "canvas limits" in diagnostic.details["attempt_history"][-1].reason


# ------------------------------------------------------------- end-to-end


def test_plan_renders_and_passes_geometry_check():
    model = model_for(make_tokens(TOKEN_ITEMS))
    plan = fit_layout(model, ShapeSpec("cat"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=never_join, ctx=context())

    rendered = render_source(model, plan, FillOptions(), ctx=context())
    _, issues = check_geometry(model, plan, rendered, None, context())
    assert not issues.reasons, issues.reasons


def test_grown_plan_renders_and_passes_geometry_check():
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(60))
    model = model_for(tokens)
    options = LayoutOptions(base_height_rows=6, max_columns=800, max_rows=600)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=build_mask, join_checker=never_join, ctx=context())
    rendered = render_source(model, plan, FillOptions(), ctx=context())
    _, issues = check_geometry(model, plan, rendered, None, context())
    assert not issues.reasons, issues.reasons
