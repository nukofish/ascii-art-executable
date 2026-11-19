"""Part C: layout engine.

The layout engine maps the source model's tokens onto B's fillable
:class:`~codeart.contracts.Mask`.  It never emits source code and never
mutates the mask: it only decides each token's cell (a
:class:`~codeart.contracts.Placement`) and records the lexical separators
that must stay blank (``protected_blanks``).

When the tokens do not fit, the engine asks ``mask_builder`` for a larger
mask, growing the cell height by ``options.growth_factor`` (default 1.25),
for at most ``options.max_attempts`` (default 12) attempts.  Every attempt
is recorded; a final failure raises :class:`StageError` carrying the
``attempt_history`` in the diagnostic details, as required by the v1.4
contract.

Before the loop, a scale-1 base mask is built and the first scale is
estimated as ``max(1, initial_scale, L/U, sqrt(T/(eta*A)))`` where ``L`` is
the longest token, ``T`` the total token width, ``U`` the longest fillable
span and ``A`` the fillable cells of the base mask (``eta = 0.75``).  The
candidate mask is built and its real dimensions are verified against the
canvas, backing off row by row when the builder's height rounding would
exceed a limit, so an estimate that would exceed the limit still tries an
in-limit size; it never starts below the base height.

Cancellation and time budgets are enforced during both mask generation and
packing, not just between attempts.  A stage-aware context is passed to the
mask builder, so work stops promptly when the budget is reached.  All retries
share one layout-stage deadline derived from ``options.layout_timeout_s`` and
bounded by the pipeline's overall deadline.  The run context is read
defensively: a duck-typed context without a ``real_deadline`` attribute still
lays out, falling back to the stage budget on the real clock.

Complete programs also check smaller valid masks after a compact fit. Spare
space on a successful mask can be redistributed within that same mask.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from itertools import accumulate
from time import monotonic

from .contracts import (
    AttemptRecord,
    Diagnostic,
    ErrorCode,
    JoinChecker,
    LayoutOptions,
    LayoutPlan,
    MaskBuilder,
    Placement,
    ShapeSpec,
    SizeRequest,
    SourceModel,
    StageError,
)
from .shapes import geometry_metrics

#: A single lexical separator occupies one cell.
_GAP_CELLS = 1

# Space on either side of a short C block comment with one visible character.
_SHORT_FILL_GAP = len(" /*x*/ ")

#: Target fill fraction (``eta``) for the area-based starting estimate: the
#: tokens are expected to occupy at most this share of the fillable cells, so
#: the estimate leaves headroom for holes and comment filler.
_AREA_FILL_TARGET = 0.75
# Complete programs probe tighter masks before adding any decoration.
_PROGRAM_AREA_FILL_TARGET = 0.85


class _LayoutContext:
    """A run-context view that also enforces the layout-stage deadline.

    It is passed to the mask builder so the stage budget is enforced *during*
    mask generation, not only after the mask returns.  It preserves the
    wrapped context's shared cancellation signal and overall pipeline
    deadline, and adds the tighter layout-stage deadline in both the injected
    clock domain and the real monotonic domain.  The real deadline is the
    fallback for deterministic callers whose clock never advances.
    """

    def __init__(self, ctx, stage_deadline: float, stage_real_deadline: float) -> None:
        self._ctx = ctx
        self._stage_deadline = stage_deadline
        self._stage_real_deadline = stage_real_deadline

    @property
    def deadline(self) -> float:
        # The effective deadline is the tighter layout-stage deadline.
        return min(self._ctx.deadline, self._stage_deadline)

    @property
    def cancel_event(self):
        return self._ctx.cancel_event

    @property
    def clock(self):
        return self._ctx.clock

    def remaining_s(self) -> float:
        return max(0.0, min(
            self.deadline - self.clock(),
            self._stage_real_deadline - monotonic(),
        ))

    def check(self) -> None:
        """Cancellation and the pipeline deadline first, then the stage budget.

        Ordering matters: explicit cancellation and the overall pipeline
        deadline are reported via the wrapped context; only then is the
        layout-specific budget checked, so a stage timeout is reported as
        ``LAYOUT_TIMEOUT``.  The budget is enforced in both the injected clock
        domain and the real monotonic domain, so a frozen test clock cannot
        suppress a real stage timeout.
        """
        self._ctx.check()  # CANCELLED or PIPELINE_TIMEOUT
        if (self.clock() >= self._stage_deadline
                or monotonic() >= self._stage_real_deadline):
            raise StageError(Diagnostic(
                ErrorCode.LAYOUT_TIMEOUT,
                "layout",
                "Layout stage exceeded its time budget",
            ))

    def raise_if_cancelled(self) -> None:
        # B's per-row hook may use this name; enforce the same full budget.
        self.check()


def _pack(mask, tokens, join_checker: JoinChecker, profile, layout_ctx):
    """Greedily pack ``tokens`` into the mask spans; return placement data.

    Returns ``(placements, protected_blanks, failure_token_index, reason)``.
    ``failure_token_index`` is ``None`` on success.  The layout context is
    checked on every iteration, so a cancellation or timeout raised by the
    join checker or by elapsed time is honoured even on the final token.
    """
    # Flatten the spans in reading order (row, then span start).
    spans = [
        (row, start, end)
        for row in range(mask.height)
        for start, end in mask.spans[row]
    ]

    placements: list[Placement] = []
    protected: set[tuple[int, int]] = set()

    span_index = 0
    cursor = spans[0][1] if spans else 0
    run_tokens: list = []

    token_index = 0
    while token_index < len(tokens):
        layout_ctx.check()

        if span_index >= len(spans):
            # No remaining span can hold the current token.
            return None, None, token_index, "no remaining span can hold the token"

        row, start, end = spans[span_index]
        token = tokens[token_index]

        # A gap is needed only when the token follows another token in the
        # same contiguous run and the checker forbids joining them.
        need_gap = 0
        if run_tokens:
            if not join_checker(tuple(run_tokens), token, profile):
                need_gap = _GAP_CELLS

        if cursor + need_gap + token.width <= end:
            # The token fits in this span.
            if need_gap:
                protected.add((row, cursor))
                cursor += need_gap
            placements.append(Placement(token.index, row, cursor))
            cursor += token.width
            if need_gap:
                # The blank starts a new whitespace-free run containing only
                # the token just placed; earlier tokens no longer join it.
                run_tokens = [token]
            else:
                # Directly joined: extend the current contiguous run.
                run_tokens.append(token)
            token_index += 1
        else:
            # The token cannot cross a hole or the span edge: retry it in
            # the next span without committing anything here.
            span_index += 1
            if span_index < len(spans):
                cursor = spans[span_index][1]
            run_tokens = []

    # Re-check after the final token: a checker may have cancelled on the last call.
    layout_ctx.check()
    return placements, frozenset(protected), None, None


def _spread_program(mask, tokens, compact, protected, ctx):
    """Use the fixed mask's remaining space without lengthening inline comments."""
    spans = [(row, start, end) for row, runs in enumerate(mask.spans)
             for start, end in runs]
    if len(tokens) < 2 or compact[-1].row == spans[-1][0]:
        return compact, protected

    # Keep every separator that was present in the lexically checked packing.
    separators = [0] + [
        int(left.row != right.row or left.col + token.width != right.col)
        for token, left, right in zip(tokens, compact, compact[1:])
    ]
    offsets = tuple(accumulate((end - start for _, start, end in spans), initial=0))
    row_starts = [offsets[i] for i, (row, _, _) in enumerate(spans)
                  if i == 0 or spans[i - 1][0] != row]

    # A backward pass reserves feasible space for the remaining tokens.
    latest = [0] * len(tokens)
    span = len(spans) - 1
    cursor = offsets[-1]
    for index in range(len(tokens) - 1, -1, -1):
        ctx.check()
        width = tokens[index].width
        if cursor < offsets[span + 1]:
            cursor -= separators[index + 1]
        while cursor - width < offsets[span]:
            span -= 1
            cursor = offsets[span + 1]
        cursor -= width
        latest[index] = cursor
    last_target = latest[-1]
    if spans[bisect_right(offsets, last_target) - 1][0] == compact[-1].row:
        return compact, protected

    last = compact[-1]
    last_span = next(i for i, (row, start, end) in enumerate(spans)
                     if row == last.row and start <= last.col < end)
    last_end = offsets[last_span] + last.col - spans[last_span][1] + tokens[-1].width
    intervals = len(tokens) - 1
    gap_count = min(intervals, (offsets[-1] - last_end) // _SHORT_FILL_GAP)
    total_width = sum(token.width for token in tokens[:-1])
    placements = []
    protected = set()
    cursor = span = used_width = 0

    for index, token in enumerate(tokens):
        ctx.check()
        span_end = offsets[span + 1]
        need_gap = separators[index] if offsets[span] < cursor < span_end else 0
        target = last_target * used_width // total_width
        next_row = bisect_right(row_starts, cursor - 1)
        # When there are enough tokens, give the next row a chance to hold code
        # before skipping ahead to catch up with the spacing target.
        if 0 < next_row < len(row_starts) and len(tokens) - index >= len(row_starts) - next_row:
            target = min(target, row_starts[next_row])
        gap_due = index > 0 and index * gap_count // intervals > (index - 1) * gap_count // intervals
        if gap_due and cursor + _SHORT_FILL_GAP + token.width <= span_end:
            target = max(target, cursor + _SHORT_FILL_GAP)
        position = max(cursor + need_gap, min(target, latest[index]))
        if position + token.width <= span_end:
            position = (cursor + _SHORT_FILL_GAP if position - cursor >= _SHORT_FILL_GAP
                        else cursor + need_gap)
        else:
            span = bisect_right(offsets, position) - 1
            while position + token.width > offsets[span + 1]:
                span += 1
                position = offsets[span]
        row, start, _ = spans[span]
        if offsets[span] < cursor < position:
            protected.add((row, start + cursor - offsets[span]))
        placements.append(Placement(token.index, row, start + position - offsets[span]))
        cursor = position + token.width
        used_width += token.width

    return placements, frozenset(protected)


def _split_filler_runs(mask, tokens, placements, ctx):
    """Break consecutive empty rows by moving a trailing token when it fits."""
    for index in range(len(placements) - 2, 0, -1):
        ctx.check()
        placement = placements[index]
        if placements[index - 1].row != placement.row:
            continue
        next_row = placements[index + 1].row
        empty_rows = [row for row in range(placement.row + 1, next_row) if mask.spans[row]]
        if not empty_rows:
            continue
        middle = (empty_rows[0] + empty_rows[-1]) / 2
        # Move a trailing token into the middle of a pure-filler run when it fits.
        candidates = [
            (row, start) for row in empty_rows for start, end in mask.spans[row]
            if end - start >= tokens[index].width
        ]
        if candidates:
            row, col = min(candidates, key=lambda cell: (abs(cell[0] - middle), -cell[0]))
            placements[index] = Placement(placement.token_index, row, col)


def _layout_limit(history, message: str) -> StageError:
    """Build the diagnosed layout failure with the retry history attached."""
    return StageError(Diagnostic(
        ErrorCode.LAYOUT_LIMIT,
        "layout",
        message,
        details={"attempt_history": tuple(history)},
    ))


def _invalid_shape(message: str, history=()) -> StageError:
    """Build an INVALID_SHAPE diagnosis for an unusable injected mask."""
    return StageError(Diagnostic(
        ErrorCode.INVALID_SHAPE,
        "layout",
        message,
        details={"attempt_history": tuple(history)},
        location="Mask.allowed",
    ))


def _with_history(exc: StageError, history) -> StageError:
    """Re-raise a stage error, preserving it but attaching the attempt history."""
    diagnostic = exc.diagnostic
    details = dict(diagnostic.details)
    details["attempt_history"] = tuple(history)
    return StageError(Diagnostic(
        diagnostic.code, diagnostic.stage, diagnostic.message,
        diagnostic.line, diagnostic.column, details, diagnostic.location,
    ))


def _estimate_start_height(
    model: SourceModel,
    shape_spec: ShapeSpec,
    options: LayoutOptions,
    mask_builder: MaskBuilder,
    layout_ctx,
) -> int:
    """Estimate the height (rows) of the first packing attempt.

    A scale-1 base mask is built first so the estimate is measured from the
    real shape rather than guessed.  With the longest token ``L``, total token
    width ``T``, longest fillable span ``U`` and fillable cells ``A``:

    * ``s_width = L / U`` guarantees a span can hold the longest token;
    * ``s_area = sqrt(T / (eta * A))`` guarantees enough total area (area
      scales with the square of the scale), targeting an ``eta`` (0.75) fill.

    The estimate is ``max(1, initial_scale, s_width, s_area)``.  A continuous
    canvas clamp then gives an upper bound, but the builder rounds the
    requested height and derives the width from that discrete height, so the
    realized mask can still exceed the canvas at the boundary.  The candidate
    mask is therefore built and verified, backing off row by row until it is
    in-limit.  The base height is itself in-limit, so the returned height is
    always at least ``base_height_rows`` and never below it.

    A base mask with no fillable cell raises ``INVALID_SHAPE`` before the
    width/area divisions, rather than a bare ``ZeroDivisionError``.
    """
    base_mask = mask_builder(
        shape_spec, SizeRequest(options.base_height_rows),
        options.font_metrics, ctx=layout_ctx)

    longest_span = 0
    fillable_cells = 0
    for row_spans in base_mask.spans:
        for start, end in row_spans:
            longest_span = max(longest_span, end - start)
            fillable_cells += end - start

    # An injected builder may return a structurally valid mask with no fillable
    # cell. Guard before the width/area divisions below (which would raise a
    # bare ZeroDivisionError) and report a structured INVALID_SHAPE instead;
    # fit_layout attaches the attempt history.
    if longest_span == 0 or fillable_cells == 0:
        raise _invalid_shape(
            "base mask has no fillable cell, so the start size cannot be estimated")

    longest_token = max(token.width for token in model.tokens)
    total_width = sum(token.width for token in model.tokens)
    fill_target = _PROGRAM_AREA_FILL_TARGET if model.program_mode else _AREA_FILL_TARGET
    scale_width = longest_token / longest_span
    scale_area = math.sqrt(total_width / (fill_target * fillable_cells))
    estimated = max(1.0, options.initial_scale, scale_width, scale_area)

    # Continuous upper bound on the scale, measured from the real base mask.
    max_scale_rows = options.max_rows / options.base_height_rows
    max_scale_cols = options.max_columns / base_mask.width
    max_in_limit_scale = min(max_scale_rows, max_scale_cols)
    candidate_height = max(
        1, math.ceil(options.base_height_rows * min(estimated, max_in_limit_scale)))

    # The builder's realized dimensions are discrete (it rounds the height and
    # derives the width), so verify the actual mask and back off until it is
    # in-limit. The base mask is guaranteed in-limit, so this always terminates.
    height = candidate_height
    while height > options.base_height_rows:
        candidate_mask = mask_builder(
            shape_spec, SizeRequest(height), options.font_metrics, ctx=layout_ctx)
        if (candidate_mask.width <= options.max_columns
                and candidate_mask.height <= options.max_rows):
            return height
        height -= 1
    return options.base_height_rows


def fit_layout(
    model: SourceModel,
    shape_spec: ShapeSpec,
    options: LayoutOptions,
    /,
    *,
    mask_builder: MaskBuilder,
    join_checker: JoinChecker,
    ctx,
) -> LayoutPlan:
    """Lay out ``model.tokens`` on a mask for ``shape_spec``.

    Args:
        model: the analyzed source, whose tokens are placed in order.
        shape_spec: which pattern the mask is built for.
        options: base height, growth factor, attempt/canvas/time limits and
            font metrics.
        mask_builder: injected B builder returning a
            :class:`~codeart.contracts.Mask`.
        join_checker: injected A checker deciding whether two adjacent
            tokens can be joined without a separator.
        ctx: the shared run context, used for cancellation and deadline.

    Returns:
        LayoutPlan for the final mask, with one placement per token, the
        protected blanks and the full attempt history. ``actual_scale`` is
        the realized ratio ``mask.height / base_height_rows`` after rounding.

    Raises:
        StageError: LAYOUT_LIMIT when every attempt fails or a grown mask
            exceeds the canvas limits; LAYOUT_TIMEOUT when the shared layout
            time budget is exceeded; CANCELLED/PIPELINE_TIMEOUT from the run
            context. Every error includes ``attempt_history`` in details.
    """
    history: list[AttemptRecord] = []
    # All retries share one layout-stage deadline, never beyond the pipeline.
    stage_deadline = min(ctx.clock() + options.layout_timeout_s, ctx.deadline)
    # The same budget is also measured on the real monotonic clock, so a
    # frozen injected clock cannot disable the stage timeout.  A context that
    # predates ``real_deadline`` (an older test or a third-party duck-typed
    # context exposing only deadline/clock/check()/cancel_event) is accepted:
    # the attribute is read defensively and a missing one falls back to the
    # stage budget measured on the real clock, exactly like ``None``.
    pipeline_real_deadline = getattr(ctx, "real_deadline", None)
    if pipeline_real_deadline is None:
        pipeline_real_deadline = monotonic() + options.layout_timeout_s
    stage_real_deadline = min(
        pipeline_real_deadline, monotonic() + options.layout_timeout_s)
    # A stage-aware context enforces the budget while the mask is built.
    layout_ctx = _LayoutContext(ctx, stage_deadline, stage_real_deadline)

    # Build a scale-1 base mask and estimate the first height from the longest
    # token and total area, so the longest token avoids pointless small-scale
    # retries. The estimate is verified against the builder's real dimensions
    # and kept inside the canvas, so an out-of-limit estimate still tries an
    # in-limit size. A failure during the base mask build (timeout/cancel)
    # still gets the history key.
    try:
        start_height = _estimate_start_height(
            model, shape_spec, options, mask_builder, layout_ctx)
    except StageError as exc:
        raise _with_history(exc, history) from exc
    start_scale = start_height / options.base_height_rows
    program_height = start_height
    min_program_height = max(options.base_height_rows, math.ceil(
        options.base_height_rows * options.initial_scale))
    best = None
    failed_height = min_program_height - 1

    for attempt in range(options.max_attempts):
        attempt_started = ctx.clock()
        mask = None
        attempt_recorded = False
        try:
            ctx.check()
            # The first attempt uses the verified in-limit height; later
            # attempts grow geometrically from the start scale.
            if model.program_mode:
                height = program_height
            elif attempt == 0:
                height = start_height
            else:
                requested_scale = start_scale * (options.growth_factor ** attempt)
                height = max(1, math.ceil(options.base_height_rows * requested_scale))

            mask = mask_builder(
                shape_spec, SizeRequest(height), options.font_metrics, ctx=layout_ctx)

            # Refuse to grow beyond the configured canvas limits.
            if mask.width > options.max_columns or mask.height > options.max_rows:
                reason = "mask exceeds the configured canvas limits"
                actual_scale = mask.height / options.base_height_rows
                history.append(AttemptRecord(
                    actual_scale, mask.width, mask.height, None, reason,
                    ctx.clock() - attempt_started))
                attempt_recorded = True
                raise _layout_limit(history, reason)

            # Some rasterized cat sizes introduce extra enclosed gaps at the ears.
            if (model.program_mode and mask.kind == "cat" and mask.height >= 32
                    and len(geometry_metrics(mask)["holes"]) != 3):
                failure_index = None
                reason = "cat mask does not have exactly three holes"
            else:
                placements, protected, failure_index, reason = _pack(
                    mask, model.tokens, join_checker, model.profile, layout_ctx)
                if model.program_mode and reason is None:
                    best = (mask, placements, protected)
                    placements, protected = _spread_program(
                        mask, model.tokens, placements, protected, layout_ctx)
                    _split_filler_runs(mask, model.tokens, placements, layout_ctx)
        except StageError as exc:
            # Record the interrupted attempt (best effort) before propagating.
            if not attempt_recorded and mask is not None:
                actual_scale = mask.height / options.base_height_rows
                history.append(AttemptRecord(
                    actual_scale, mask.width, mask.height, None,
                    f"{exc.diagnostic.code.value}: {exc.diagnostic.message}",
                    ctx.clock() - attempt_started))
            if best is not None and exc.diagnostic.code == ErrorCode.LAYOUT_TIMEOUT:
                break
            raise _with_history(exc, history) from exc

        # The elapsed time covers both mask generation and token packing.
        elapsed = ctx.clock() - attempt_started
        actual_scale = mask.height / options.base_height_rows

        failed_token_index = (model.tokens[failure_index].index
                              if failure_index is not None else None)
        history.append(AttemptRecord(
            actual_scale, mask.width, mask.height, failed_token_index, reason, elapsed))
        if reason is None:
            best = (mask, placements, protected)
            if not model.program_mode:
                break
        if model.program_mode:
            if best is None:
                if failure_index is not None:
                    failed_height = height
                    # Estimate a small increase from the unplaced portion near a fit.
                    if failure_index < len(model.tokens) * 7 / 8:
                        growth = options.growth_factor
                    else:
                        growth = math.sqrt(len(model.tokens) / failure_index)
                    program_height = max(height + 1, math.ceil(height * growth))
                else:
                    program_height = height + 1
            else:
                if height <= failed_height + 1 or failure_index is not None:
                    break
                program_height = height - 1

    if best is not None:
        mask, placements, protected = best
        return LayoutPlan(
            mask=mask,
            placements=tuple(placements),
            protected_blanks=protected,
            actual_scale=mask.height / options.base_height_rows,
            attempt_count=len(history),
            attempt_history=tuple(history),
        )

    raise _layout_limit(history, "all layout attempts were exhausted")
