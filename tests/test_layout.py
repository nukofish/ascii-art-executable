"""Part C tests: token placement, protected blanks, bounded retries and errors."""

from __future__ import annotations

import time
from threading import Event
from time import monotonic

import pytest

from codeart import FontMetrics, Mask, ShapeSpec, build_mask
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
    # Scales are realized from the rounded mask height, not the requested
    # factor, so each record's scale equals its height divided by the base.
    for record in plan.attempt_history:
        assert record.scale == pytest.approx(record.height / options.base_height_rows)
        assert record.scale >= 1.0


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


# ------------------------------------------------------------- P1 cancellation / timeout


def test_cancellation_in_join_checker_stops_layout():
    tokens = make_tokens([("identifier", "a"), ("identifier", "b"), ("identifier", "c")])
    model = model_for(tokens)
    event = Event()

    def cancelling_checker(run, nxt, profile):
        event.set()  # trigger cancellation during a join check
        return False

    ctx = RunContext(monotonic() + 30, event)
    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                   mask_builder=build_mask, join_checker=cancelling_checker, ctx=ctx)
    assert exc_info.value.diagnostic.code == ErrorCode.CANCELLED


def test_layout_stage_timeout_raises_layout_timeout():
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(40))
    model = model_for(tokens)

    def slow_checker(run, nxt, profile):
        time.sleep(0.01)  # make the lexical decision consume the tiny budget
        return False

    options = LayoutOptions(layout_timeout_s=0.001)
    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=slow_checker, ctx=context())

    diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_TIMEOUT
    assert len(diagnostic.details["attempt_history"]) >= 1


def test_layout_timeout_is_shared_across_retries():
    # A small base mask forces growth; the absolute stage deadline must not
    # be reset when a new attempt starts.
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(300))
    model = model_for(tokens)

    def slow_checker(run, nxt, profile):
        time.sleep(0.01)
        return True

    options = LayoutOptions(base_height_rows=4, layout_timeout_s=0.001,
                            max_columns=800, max_rows=600)
    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=slow_checker, ctx=context())
    assert exc_info.value.diagnostic.code == ErrorCode.LAYOUT_TIMEOUT


def test_mask_building_respects_layout_stage_budget():
    clock_state = {"t": 0.0}

    def fake_clock():
        return clock_state["t"]

    overall = RunContext(deadline=100.0, clock=fake_clock)

    def slow_mask_builder(shape_spec, size_request, font_metrics, *, ctx):
        # Simulate one second of work per iteration, checking the context.
        for _ in range(10):
            clock_state["t"] += 1.0
            ctx.check()
        # Reaching here means the stage budget was not enforced during generation.
        return _rect_mask(5)

    tokens = make_tokens([("identifier", "a")])
    model = model_for(tokens)
    options = LayoutOptions(layout_timeout_s=2.0)

    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=slow_mask_builder,
                   join_checker=always_join, ctx=overall)

    diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_TIMEOUT
    # The builder must stop at the 2-second mark, not run all 10 seconds.
    assert fake_clock() == 2.0
    assert "attempt_history" in diagnostic.details


def test_elapsed_time_includes_token_packing():
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(20))
    model = model_for(tokens)

    def slow_checker(run, nxt, profile):
        if run:
            time.sleep(0.005)
        return True

    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=slow_checker, ctx=context())
    # The successful record must account for the packing sleeps, not just the
    # (near-instant) mask generation.
    assert plan.attempt_history[-1].elapsed_s >= 0.05


# ------------------------------------------------------------- P2 run reset


def _rect_mask(width, height=1):
    allowed = tuple(tuple(True for _ in range(width)) for _ in range(height))
    spans = tuple(((0, width),) for _ in range(height))
    return Mask(kind="rect", width=width, height=height, allowed=allowed,
                spans=spans, scale=1.0, font_metrics=FontMetrics())


def test_separator_resets_the_contiguous_run():
    width = 5
    tokens = make_tokens([
        ("identifier", "a"), ("identifier", "b"),
        ("punctuator", "+"), ("identifier", "c"),
    ])
    model = model_for(tokens)

    def fixed_builder(shape_spec, size_request, font_metrics, *, ctx):
        return _rect_mask(width)

    def strict_checker(run, nxt, profile):
        if not run:
            return True
        word = lambda t: t.kind in ("identifier", "keyword")
        # A whitespace-free run must not already contain a word-word join.
        for left, right in zip(run, run[1:]):
            if word(left) and word(right):
                return False
        return not (word(run[-1]) and word(nxt))

    # The buggy engine returned LAYOUT_LIMIT here; the fixed one fits "a b+c".
    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=fixed_builder, join_checker=strict_checker, ctx=context())
    assert len(plan.placements) == 4
    assert (0, 1) in plan.protected_blanks
    assert [p.col for p in plan.placements] == [0, 2, 3, 4]


# ------------------------------------------------------------- P2 actual scale


def test_actual_scale_reflects_rounded_height():
    tokens = make_tokens([("identifier", "a")])
    model = model_for(tokens)
    options = LayoutOptions(base_height_rows=32, initial_scale=1.01)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=build_mask, join_checker=always_join, ctx=context())

    assert plan.mask.height == 33
    assert plan.actual_scale == pytest.approx(33 / 32)
    assert plan.attempt_history[0].scale == pytest.approx(33 / 32)
