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

Cancellation and time budgets are enforced while packing, not just between
attempts.  All retries share one layout-stage deadline derived from
``options.layout_timeout_s`` and bounded by the pipeline's overall deadline.
"""

from __future__ import annotations

import math

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

#: A single lexical separator occupies one cell.
_GAP_CELLS = 1


def _guard(ctx, stage_deadline: float) -> None:
    """Respect cancellation, the pipeline deadline and the layout-stage budget.

    Ordering matters: explicit cancellation and the overall pipeline deadline
    are reported first via ``ctx.check()``; only then is the layout-specific
    budget checked, so a stage timeout is reported as ``LAYOUT_TIMEOUT``.
    """
    ctx.check()  # CANCELLED or PIPELINE_TIMEOUT
    if ctx.clock() >= stage_deadline:
        raise StageError(Diagnostic(
            ErrorCode.LAYOUT_TIMEOUT,
            "layout",
            "Layout stage exceeded its time budget",
        ))


def _pack(mask, tokens, join_checker: JoinChecker, profile, ctx, stage_deadline):
    """Greedily pack ``tokens`` into the mask spans; return placement data.

    Returns ``(placements, protected_blanks, failure_token_index, reason)``.
    ``failure_token_index`` is ``None`` on success.  The guard runs on every
    iteration, so a cancellation or timeout raised by the join checker or by
    elapsed time is honoured even on the final token.
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
        _guard(ctx, stage_deadline)

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
    _guard(ctx, stage_deadline)
    return placements, frozenset(protected), None, None


def _layout_limit(history, message: str) -> StageError:
    """Build the diagnosed layout failure with the retry history attached."""
    return StageError(Diagnostic(
        ErrorCode.LAYOUT_LIMIT,
        "layout",
        message,
        details={"attempt_history": tuple(history)},
    ))


def _with_history(exc: StageError, history) -> StageError:
    """Re-raise a stage error, preserving it but attaching the attempt history."""
    diagnostic = exc.diagnostic
    details = dict(diagnostic.details)
    details["attempt_history"] = tuple(history)
    return StageError(Diagnostic(
        diagnostic.code, diagnostic.stage, diagnostic.message,
        diagnostic.line, diagnostic.column, details,
    ))


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

    for attempt in range(options.max_attempts):
        attempt_started = ctx.clock()
        mask = None
        attempt_recorded = False
        try:
            ctx.check()
            requested_scale = options.initial_scale * (options.growth_factor ** attempt)
            height = max(1, math.ceil(options.base_height_rows * requested_scale))

            mask = mask_builder(
                shape_spec, SizeRequest(height), options.font_metrics, ctx=ctx)

            # Refuse to grow beyond the configured canvas limits.
            if mask.width > options.max_columns or mask.height > options.max_rows:
                reason = "mask exceeds the configured canvas limits"
                actual_scale = mask.height / options.base_height_rows
                history.append(AttemptRecord(
                    actual_scale, mask.width, mask.height, None, reason,
                    ctx.clock() - attempt_started))
                attempt_recorded = True
                raise _layout_limit(history, reason)

            placements, protected, failure_index, reason = _pack(
                mask, model.tokens, join_checker, model.profile, ctx, stage_deadline)
        except StageError as exc:
            # Record the interrupted attempt (best effort) before propagating.
            if not attempt_recorded and mask is not None:
                actual_scale = mask.height / options.base_height_rows
                history.append(AttemptRecord(
                    actual_scale, mask.width, mask.height, None,
                    f"{exc.diagnostic.code.value}: {exc.diagnostic.message}",
                    ctx.clock() - attempt_started))
            raise _with_history(exc, history) from exc

        # The elapsed time covers both mask generation and token packing.
        elapsed = ctx.clock() - attempt_started
        actual_scale = mask.height / options.base_height_rows

        if failure_index is None:
            # Record the successful attempt, then return the plan.
            history.append(AttemptRecord(
                actual_scale, mask.width, mask.height, None, None, elapsed))
            return LayoutPlan(
                mask=mask,
                placements=tuple(placements),
                protected_blanks=protected,
                actual_scale=actual_scale,
                attempt_count=attempt + 1,
                attempt_history=tuple(history),
            )

        failed_token = model.tokens[failure_index]
        history.append(AttemptRecord(
            actual_scale, mask.width, mask.height,
            failed_token.index, reason, elapsed))

    raise _layout_limit(history, "all layout attempts were exhausted")
