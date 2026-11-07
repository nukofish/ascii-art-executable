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
"""

from __future__ import annotations

import math
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

#: A single lexical separator occupies one cell.
_GAP_CELLS = 1


def _pack(mask, tokens, join_checker: JoinChecker, profile):
    """Greedily pack ``tokens`` into the mask spans; return placement data.

    Returns ``(placements, protected_blanks, failure_token_index, reason)``.
    ``failure_token_index`` is ``None`` on success.
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
            run_tokens.append(token)
            token_index += 1
        else:
            # The token cannot cross a hole or the span edge: retry it in
            # the next span without committing anything here.
            span_index += 1
            if span_index < len(spans):
                cursor = spans[span_index][1]
            run_tokens = []

    return placements, frozenset(protected), None, None


def _layout_limit(history, message: str) -> StageError:
    """Build the diagnosed layout failure with the retry history attached."""
    return StageError(Diagnostic(
        ErrorCode.LAYOUT_LIMIT,
        "layout",
        message,
        details={"attempt_history": tuple(history)},
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
        options: base height, growth factor, attempt/canvas limits and font
            metrics.
        mask_builder: injected B builder returning a
            :class:`~codeart.contracts.Mask`.
        join_checker: injected A checker deciding whether two adjacent
            tokens can be joined without a separator.
        ctx: the shared run context, used for cancellation and deadline.

    Returns:
        LayoutPlan for the final mask, with one placement per token, the
        protected blanks and the full attempt history.

    Raises:
        StageError: LAYOUT_LIMIT when every attempt fails or a grown mask
            exceeds the configured canvas limits; ``attempt_history`` is
            included in ``diagnostic.details``.
    """
    history: list[AttemptRecord] = []

    for attempt in range(options.max_attempts):
        ctx.check()
        scale = options.initial_scale * (options.growth_factor ** attempt)
        height = max(1, math.ceil(options.base_height_rows * scale))

        started = monotonic()
        mask = mask_builder(
            shape_spec, SizeRequest(height), options.font_metrics, ctx=ctx)
        elapsed = monotonic() - started

        # Refuse to grow beyond the configured canvas limits.
        if mask.width > options.max_columns or mask.height > options.max_rows:
            record = AttemptRecord(
                scale, mask.width, mask.height, None,
                "mask exceeds the configured canvas limits", elapsed)
            history.append(record)
            raise _layout_limit(history, record.reason)

        placements, protected, failure_index, reason = _pack(
            mask, model.tokens, join_checker, model.profile)

        if failure_index is None:
            # Record the successful attempt, then return the plan.
            history.append(AttemptRecord(
                scale, mask.width, mask.height, None, None, elapsed))
            return LayoutPlan(
                mask=mask,
                placements=tuple(placements),
                protected_blanks=protected,
                actual_scale=scale,
                attempt_count=attempt + 1,
                attempt_history=tuple(history),
            )

        failed_token = model.tokens[failure_index]
        history.append(AttemptRecord(
            scale, mask.width, mask.height, failed_token.index, reason, elapsed))

    raise _layout_limit(history, "all layout attempts were exhausted")
