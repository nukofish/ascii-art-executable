"""Part C tests: token placement, protected blanks, bounded retries and errors."""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import replace
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
from codeart.source import analyze_source, can_join


CLANG = shutil.which("clang")
try:
    import clang.cindex  # noqa: F401

    HAS_LIBCLANG = True
except Exception:
    HAS_LIBCLANG = False
requires_clang = pytest.mark.skipif(
    CLANG is None or not HAS_LIBCLANG,
    reason="Clang and libclang are required",
)


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


@pytest.mark.parametrize("count, height", ((40, 4), (26, 6)))
def test_program_uses_smallest_requested_canvas_and_short_fill(count, height):
    tokens = make_tokens([("identifier", "abc")] * count)
    model = replace(model_for(tokens), program_mode=True)
    options = LayoutOptions(base_height_rows=height)

    def rectangle(shape, size, font, *, ctx):
        return _rect_mask(40, size.height_rows)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=rectangle, join_checker=never_join, ctx=context())
    assert plan.mask.height == height
    assert {placement.row for placement in plan.placements} == set(range(height))
    rendered = render_source(model, plan, FillOptions(), ctx=context())
    internal_gaps = [
        right.col - left.col - tokens[index].width
        for index, (left, right) in enumerate(zip(plan.placements, plan.placements[1:]))
        if left.row == right.row
    ]
    assert max(internal_gaps) <= len(" /*x*/ ")
    if count == 40:
        assert "/*" not in rendered.source_text
    else:
        fillers = re.findall(r"abc /\*(.)\*/ (?=abc)", rendered.source_text)
        assert len(set(fillers)) >= 3


def test_program_moves_a_token_to_break_consecutive_filler_rows():
    widths = (12, 4, 4, 16)
    mask = replace(
        _rect_mask(16, 4),
        allowed=tuple(tuple(col < width for col in range(16)) for width in widths),
        spans=tuple(((0, width),) for width in widths),
    )
    tokens = make_tokens([("identifier", text) for text in ("abc", "b", "c", "longlonglong")])
    model = replace(model_for(tokens), program_mode=True)
    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(base_height_rows=4),
                      mask_builder=lambda *args, **kwargs: mask, join_checker=never_join,
                      ctx=context())
    assert [placement.row for placement in plan.placements] == [0, 1, 2, 3]


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
    # A builder that always returns a 5-wide mask (ignoring the requested
    # height) means the width-10 token can never fit; the loop runs all
    # max_attempts and then raises LAYOUT_LIMIT with the full history.
    wide = Token(0, "identifier", "w" * 10, 10, 1, 1)
    model = model_for((wide,))
    options = LayoutOptions(base_height_rows=4, max_attempts=3,
                            max_columns=800, max_rows=600)

    def fixed_builder(shape_spec, size_request, font_metrics, *, ctx):
        return _rect_mask(5)

    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=fixed_builder, join_checker=always_join, ctx=context())

    diagnostic: Diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_LIMIT
    assert diagnostic.stage == "layout"
    history = diagnostic.details["attempt_history"]
    assert len(history) == 3
    assert all(record.failure_token_index == 0 for record in history)


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

    # The 50 ms budget covers the scale-1 base mask build of the estimate, yet
    # is still exhausted during the first packing attempt (each join sleeps).
    options = LayoutOptions(layout_timeout_s=0.05)
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


def test_layout_timeout_is_honored_with_a_frozen_clock():
    # Deterministic callers freeze the injected clock, so the clock-only
    # deadline never fires.  The real monotonic fallback must still stop the
    # stage instead of letting the slow join checks run to completion.
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(40))
    model = model_for(tokens)

    def slow_checker(run, nxt, profile):
        time.sleep(0.02)
        return False

    ctx = RunContext(deadline=100.0, clock=lambda: 0.0)
    options = LayoutOptions(base_height_rows=4, layout_timeout_s=0.01,
                            max_columns=800, max_rows=600)
    started = time.monotonic()
    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=slow_checker, ctx=ctx)
    elapsed = time.monotonic() - started

    assert exc_info.value.diagnostic.code == ErrorCode.LAYOUT_TIMEOUT
    assert 0.01 <= elapsed < 0.5


def test_frozen_clock_real_budget_stops_the_stage_within_the_first_attempt():
    # Complements the deterministic shared-budget regression below: when the
    # injected clock is frozen, the real monotonic fallback must still stop the
    # stage during the first attempt instead of letting all three attempts run.
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(300))
    model = model_for(tokens)

    def slow_checker(run, nxt, profile):
        time.sleep(0.012)
        return True

    ctx = RunContext(deadline=100.0, clock=lambda: 0.0)
    options = LayoutOptions(base_height_rows=4, layout_timeout_s=0.01,
                            max_attempts=3, max_columns=800, max_rows=600)
    started = time.monotonic()
    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=slow_checker, ctx=ctx)
    elapsed = time.monotonic() - started

    assert exc_info.value.diagnostic.code == ErrorCode.LAYOUT_TIMEOUT
    assert elapsed < 0.01 * 2.5


def test_layout_budget_is_not_reset_for_the_second_attempt():
    # Deterministic, discriminating regression for the budget shared by all
    # retries. The injected clock advances only when a retry attempt builds its
    # mask: +6 ms on the first attempt and +5 ms on the second (11 ms in
    # total). The first attempt therefore stays inside the 10 ms budget and
    # fails for capacity, while the second one is already past it.
    #
    # This is what the old ``time.sleep(0.012)`` version could not prove: there
    # the very first attempt burned the whole budget, so an implementation that
    # reset the budget per attempt still reported LAYOUT_TIMEOUT and the test
    # passed. Here such an implementation would give the second attempt a fresh
    # 10 ms deadline at t=6 ms, so its 5 ms advance would stay inside it, the
    # wide token would still fail for capacity, all three attempts would be
    # exhausted, and the final error would be LAYOUT_LIMIT - which fails the
    # LAYOUT_TIMEOUT assertion below.
    wide = Token(0, "identifier", "w" * 100, 100, 1, 1)
    model = model_for((wide,))
    clock = {"t": 0.0}
    ctx = RunContext(deadline=100.0, clock=lambda: clock["t"])

    # The estimator builds one scale-1 probe mask before the retry loop (no
    # growth is possible: max_rows == base_height_rows), so call 0 is that
    # probe and calls 1..2 are the first two attempts.
    schedule = (0.0, 0.006, 0.005)
    calls = {"n": 0}

    def ticking_builder(shape_spec, size_request, font_metrics, *, ctx):
        call = calls["n"]
        calls["n"] += 1
        if call < len(schedule):
            clock["t"] += schedule[call]
        return _rect_mask(5)  # 5 cells wide: the 100-cell token never fits

    options = LayoutOptions(base_height_rows=4, layout_timeout_s=0.01,
                            max_attempts=3, max_columns=800, max_rows=4)
    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=ticking_builder, join_checker=always_join, ctx=ctx)

    diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_TIMEOUT
    history = diagnostic.details["attempt_history"]
    # The first attempt really ran, recorded a capacity failure (not a
    # timeout) and is followed by the attempt that hit the shared deadline.
    assert len(history) >= 1
    assert history[0].failure_token_index == 0
    assert history[0].elapsed_s == pytest.approx(0.006)
    assert history[-1].reason.startswith(ErrorCode.LAYOUT_TIMEOUT.value)
    assert 0.01 <= clock["t"] < 0.02
    assert clock["t"] == pytest.approx(0.011)


# --------------------------------------------------- default layout budget


@requires_clang
def test_default_layout_budget_fits_a_real_sized_program():
    """Exercise the default budget with a large function and the public join checker."""
    lines = ["int big(int seed) {", "    int a = seed;", "    int b = 0;"]
    for i in range(120):
        lines += [f"    b = b + a * {i} + ({i} % 7);",
                  f"    if (b > {i*10}) {{ a = a - {i}; }} else {{ a = a + {i}; }}"]
    lines += ["    return a + b;", "}"]
    program = "\n".join(lines) + "\n"

    model = analyze_source(program)
    assert len(model.tokens) > 4000  # the measured 4463-token / ~243-line case

    plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=can_join,
                      ctx=context(120))

    assert [p.token_index for p in plan.placements] == [t.index for t in model.tokens]
    assert len(plan.placements) == len(model.tokens)


def test_default_layout_budget_stays_at_sixty_seconds():
    assert LayoutOptions().layout_timeout_s == 60.0


# ------------------------------------------------------- legacy run contexts


class LegacyContext:
    """The duck type an older test or third-party caller passes to the stages.

    It provides everything ``fit_layout`` reads - ``deadline``, ``clock``,
    ``check()``, ``cancel_event`` and ``remaining_s()`` - but it predates
    ``real_deadline``, which a real :class:`RunContext` derives at construction.
    """

    def __init__(self, deadline, clock=monotonic):
        self.deadline = deadline
        self.clock = clock
        self.cancel_event = None

    def remaining_s(self):
        return max(0.0, self.deadline - self.clock())

    def check(self):
        if self.remaining_s() == 0:
            raise StageError(Diagnostic(
                ErrorCode.PIPELINE_TIMEOUT, "pipeline", "Generation timed out"))


#: Error codes ``fit_layout`` may legitimately end a run with. Anything else,
#: in particular an ``AttributeError`` escaping instead of a ``StageError``, is
#: a regression.
LAYOUT_ERROR_CODES = frozenset({
    ErrorCode.LAYOUT_LIMIT,
    ErrorCode.LAYOUT_TIMEOUT,
    ErrorCode.INVALID_SHAPE,
    ErrorCode.CANCELLED,
    ErrorCode.PIPELINE_TIMEOUT,
})


def test_layout_accepts_legacy_context_without_real_deadline():
    # Regression: fit_layout used to read ``ctx.real_deadline`` directly, so a
    # duck-typed context without that attribute (older fixtures, third-party
    # callers) raised AttributeError before the first attempt. The attribute is
    # now read with getattr, so the layout completes - or fails with one of its
    # own diagnosed codes - instead of blowing up with AttributeError.
    model = model_for(make_tokens(TOKEN_ITEMS))
    legacy = LegacyContext(monotonic() + 30)
    assert not hasattr(legacy, "real_deadline")

    try:
        plan = fit_layout(model, ShapeSpec("circle"), LayoutOptions(),
                          mask_builder=build_mask, join_checker=never_join, ctx=legacy)
    except StageError as exc:
        # A legacy context may still end in a diagnosed stage error, never in
        # an AttributeError surfacing as the failure's diagnostic.
        assert not isinstance(getattr(exc, "diagnostic", None), AttributeError)
        assert exc.diagnostic.code in LAYOUT_ERROR_CODES
    else:
        assert len(plan.placements) == len(model.tokens)
        assert plan.attempt_count >= 1


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
                spans=spans, font_metrics=FontMetrics())


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


# ------------------------------------------------- integration hardening (CODE / long tokens)


def test_code_mask_packs_tokens_across_many_short_spans():
    # The first four rows are single full-width spans (178 cells); from row 4
    # the mask is fragmented into short 5-8 cell spans. Use enough tokens to
    # reach that fragmented region and assert tokens flow across the short spans.
    token_count = 1200
    tokens = tuple(Token(i, "identifier", "v", 1, 1, 1) for i in range(token_count))
    model = model_for(tokens)

    plan = fit_layout(model, ShapeSpec("code"), LayoutOptions(),
                      mask_builder=build_mask, join_checker=always_join, ctx=context())

    assert plan.mask.width == 178
    assert len(plan.placements) == token_count
    mask = plan.mask

    # At least one occupied row is a fragmented multi-span row.
    occupied_rows = {p.row for p in plan.placements}
    fragmented_rows = [r for r in occupied_rows if len(mask.spans[r]) > 1]
    assert fragmented_rows, "no token reached the fragmented spans"

    def span_index_of(row, col):
        for idx, (start, end) in enumerate(mask.spans[row]):
            if start <= col < end:
                return idx
        raise AssertionError("col outside the row's spans")

    # On a fragmented row, tokens flow across at least two distinct spans.
    cross_span = False
    for row in fragmented_rows:
        cols = [p.col for p in plan.placements if p.row == row]
        if len({span_index_of(row, col) for col in cols}) >= 2:
            cross_span = True
            break
    assert cross_span, "tokens never crossed between the short spans"

    # Every token sits on an allowed cell inside one of the row's spans.
    for placement in plan.placements:
        row, col = placement.row, placement.col
        assert mask.allowed[row][col]
        assert any(start <= col < end for start, end in mask.spans[row])


def test_longest_token_gets_a_large_enough_start_via_estimate():
    # A width-12 token is wider than every span of the h=4 base mask (max 8).
    # The width estimate (L/U = 12/8 = 1.5) moves the first attempt to h=6,
    # whose full-width span holds the token, so no small-scale retries are wasted.
    wide = Token(0, "identifier", "w" * 12, 12, 1, 1)
    model = model_for((wide,))
    options = LayoutOptions(base_height_rows=4, max_columns=800, max_rows=600)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=build_mask, join_checker=always_join, ctx=context())

    assert plan.attempt_count == 1
    assert plan.mask.height == 6
    assert len(plan.placements) == 1
    row, col = plan.placements[0].row, plan.placements[0].col
    # All 12 cells are allowed and contained within a single span.
    assert all(plan.mask.allowed[row][col:col + 12])
    assert any(start <= col and col + 12 <= end
               for start, end in plan.mask.spans[row])

    # The plan still renders and passes the geometry contract.
    rendered = render_source(model, plan, FillOptions(), ctx=context())
    _, issues = check_geometry(model, plan, rendered, None, context())
    assert not issues.reasons, issues.reasons


def test_long_token_that_never_fits_raises_layout_limit_with_history():
    # A token wider than the maximum canvas width (801 > max_columns 800) can
    # never fit any valid mask. The estimate is clamped to the largest in-limit
    # mask (h=400), which confirms the token cannot pack; the next growth
    # exceeds the canvas, so it is diagnosed as LAYOUT_LIMIT with history.
    wide = Token(0, "identifier", "w" * 801, 801, 1, 1)
    model = model_for((wide,))
    options = LayoutOptions(base_height_rows=4, max_attempts=12,
                            max_columns=800, max_rows=600)

    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=build_mask, join_checker=always_join, ctx=context())

    diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.LAYOUT_LIMIT
    history = diagnostic.details["attempt_history"]
    assert len(history) >= 1
    # The first record is an in-limit packing failure (token 0); the later
    # record is a canvas limit (token None).
    assert all(record.failure_token_index in (None, 0) for record in history)
    assert any(record.failure_token_index == 0 for record in history)


def test_out_of_limit_estimate_still_tries_an_in_limit_canvas():
    # Regression for the first estimate attempt: on a 4x8 canvas with 24
    # single-cell semicolons, the area estimate asks for a 5-row mask (beyond
    # max_rows). An out-of-limit estimate cannot prove the in-limit mask
    # fails, so the start is clamped to scale 1 and the tokens must fit in the
    # 4-row canvas instead of raising LAYOUT_LIMIT.
    tokens = tuple(Token(i, "punct", ";", 1, 1, 1) for i in range(24))
    model = model_for(tokens)
    options = LayoutOptions(base_height_rows=4, max_attempts=12,
                            max_columns=8, max_rows=4)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=build_mask, join_checker=always_join, ctx=context())

    assert plan.attempt_count == 1
    assert plan.mask.height == 4
    assert plan.mask.width == 8
    assert len(plan.placements) == 24
    # Every placement sits on an allowed cell inside the 4-row canvas.
    for placement in plan.placements:
        assert 0 <= placement.row < 4
        assert plan.mask.allowed[placement.row][placement.col]


def test_column_cap_rounding_still_tries_an_in_limit_canvas():
    # Regression for the column boundary: with a 4x8 base mask and
    # max_columns=9, the continuous clamp (9/8 = 1.125) rounds the height up
    # to 5 rows, and the realized circle mask at 5 rows is 5x10 — over the
    # 9-column cap. The estimate must account for the builder's real
    # dimensions after rounding and back off to the in-limit 4x8 mask that
    # fits all 24 tokens, instead of raising LAYOUT_LIMIT.
    tokens = tuple(Token(i, "punct", ";", 1, 1, 1) for i in range(24))
    model = model_for(tokens)
    options = LayoutOptions(base_height_rows=4, max_attempts=12,
                            max_columns=9, max_rows=600)

    plan = fit_layout(model, ShapeSpec("circle"), options,
                      mask_builder=build_mask, join_checker=always_join, ctx=context())

    assert plan.attempt_count == 1
    assert plan.mask.height == 4
    assert plan.mask.width == 8
    assert plan.mask.width <= 9
    assert len(plan.placements) == 24
    # Every placement sits on an allowed cell inside the in-limit mask.
    for placement in plan.placements:
        assert 0 <= placement.row < plan.mask.height
        assert plan.mask.allowed[placement.row][placement.col]


def test_empty_base_mask_raises_invalid_shape_with_history():
    # Regression for an injected builder returning a structurally valid mask
    # with no fillable cell: the estimate must not divide by zero. It raises a
    # structured INVALID_SHAPE and still carries the (empty) attempt history.
    tokens = (Token(0, "identifier", "w", 1, 1, 1),)
    model = model_for(tokens)
    options = LayoutOptions(base_height_rows=4)

    def empty_builder(shape_spec, size_request, font_metrics, *, ctx):
        rows = size_request.height_rows
        allowed = tuple(tuple(False for _ in range(4)) for _ in range(rows))
        return Mask(kind="circle", width=4, height=rows, allowed=allowed,
                    spans=tuple(() for _ in range(rows)),
                    font_metrics=FontMetrics())

    with pytest.raises(StageError) as exc_info:
        fit_layout(model, ShapeSpec("circle"), options,
                   mask_builder=empty_builder, join_checker=always_join, ctx=context())

    diagnostic: Diagnostic = exc_info.value.diagnostic
    assert diagnostic.code == ErrorCode.INVALID_SHAPE
    assert diagnostic.stage == "layout"
    assert "attempt_history" in diagnostic.details
    assert diagnostic.details["attempt_history"] == ()
