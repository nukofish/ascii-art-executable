# Module C — layout engine (`codeart/layout.py`)

C decides where every token of the analyzed source sits on B's fillable
:class:`~codeart.contracts.Mask`. It emits no source code and never mutates a
mask: it only produces one :class:`~codeart.contracts.Placement` per token and
records the lexical separators that must stay blank (`protected_blanks`).
D later writes the tokens at those placements and fills the remaining cells.

## Interface

```python
from codeart.layout import fit_layout

plan = fit_layout(
    model,       # SourceModel: tokens in order, plus the verification profile
    shape_spec,  # ShapeSpec: which pattern the mask is built for
    options,     # LayoutOptions: base height, growth, attempt/canvas/time limits
    mask_builder=build_mask,  # injected B builder returning a Mask
    join_checker=can_join,    # injected A checker for lexical separators
    ctx=ctx,                  # RunContext: cancellation and deadline
)
```

| type | fields used |
|---|---|
| `SourceModel` | `tokens` (`index`, `kind`, `spelling`, `width`), `profile` |
| `ShapeSpec` | the pattern kind passed to `mask_builder` |
| `LayoutOptions` | `base_height_rows`, `initial_scale`, `growth_factor`, `max_attempts`, `max_columns`, `max_rows`, `layout_timeout_s`, `font_metrics` |
| `Mask` | `width`, `height`, `allowed`, `spans` |
| `LayoutPlan` | `mask`, `placements`, `protected_blanks`, `actual_scale`, `attempt_count`, `attempt_history` |

## Packing rules

1. The mask's spans are flattened in reading order (row, then span start). A
   token is always placed inside a single span, so it never crosses a hole or a
   span edge.
2. A separator is added only when two tokens share a contiguous run and the
   injected `join_checker` forbids joining them. The blank is recorded in
   `protected_blanks`; the first token of each span starts a fresh run.
3. After a separator the contiguous run is reset to the current token. Directly
   joined tokens extend the run, so the checker always sees the real
   whitespace-free prefix.
4. When a token does not fit the current span, the engine moves to the next
   span without committing anything; when no span can hold it, the attempt
   fails and reports that token's index.

## Initial size estimate

Before the retry loop, the engine builds a scale-1 base mask and measures it
so the first attempt starts at a realistically large size instead of wasting
retries on small masks. From the base mask it takes the longest fillable
span `U` and the total fillable cells `A`; from the tokens it takes the
longest token `L` and the total token width `T`. The estimated scale is

```
s_est = max(1, initial_scale, L / U, sqrt(T / (eta * A)))
```

with `eta = 0.75` (the expected fill fraction). `L/U` guarantees a span can
hold the longest token; `sqrt(T/(eta*A))` guarantees enough total area (area
scales with the square of the scale).

### Clamping to the canvas

The estimate only chooses which size to try first; it cannot prove that an
in-limit mask fails. A continuous upper bound is measured from the real base
mask,

```
max_in_limit = min(max_rows/base_height_rows, max_columns/base_mask.width)
```

but the builder rounds the requested height to an integer and derives the
width from that discrete height, so the realized mask can still exceed the
canvas at the boundary (for a circle, a 4x8 base and `max_columns=9` give
`9/8 = 1.125`, which rounds to 5 rows and a 5x10 mask). The candidate mask
is therefore built and its real dimensions are verified, backing off row by
row until the mask is in-limit:

```
h_start = largest height <= ceil(base_height_rows * min(s_est, max_in_limit))
          whose realized mask fits max_rows and max_columns
```

When the estimate would exceed the canvas, the engine therefore still tries
an in-limit size (down to the base height) and only fails if that genuinely
cannot pack; it never raises `LAYOUT_LIMIT` solely because the estimate was
out of limit.

If the base mask has no fillable cell (an injected builder returned an empty
mask), the engine raises `INVALID_SHAPE` before the width and area divisions,
instead of a bare `ZeroDivisionError`; the diagnostic still carries the
attempt history.

## Automatic growth

When an attempt fails, the engine asks the builder for a larger mask. The
first attempt uses the verified start height; later attempts request
`ceil(base_height_rows * (h_start/base_height_rows) * growth_factor ** attempt)`,
with `growth_factor = 1.25` and at most `max_attempts = 12` attempts. A
grown mask whose width exceeds `max_columns` (800) or height exceeds
`max_rows` (600) is rejected with `LAYOUT_LIMIT`.

`actual_scale` is the realized ratio `mask.height / base_height_rows`, computed
after height rounding, so a base of 32 rounded to 33 rows reports
`1.03125`, not the requested factor. Every attempt uses the same definition.

## Cancellation and time budgets

A single layout-stage deadline is derived once as
`min(clock + layout_timeout_s, ctx.deadline)` and is shared by all retries. A
`_LayoutContext` wraps the run context with that deadline and is passed to both
the mask builder and the packer, so the budget is enforced *during* mask
generation and on every token, not just between attempts.

- Explicit cancellation and the overall pipeline deadline are reported as
  `CANCELLED` / `PIPELINE_TIMEOUT` through the wrapped context.
- Running past the layout-stage deadline is reported as `LAYOUT_TIMEOUT`.
- Each attempt's `elapsed_s` covers both mask generation and token packing.

## Attempt history

Every attempt is recorded as an
:class:`~codeart.contracts.AttemptRecord` with `scale`, `width`, `height`,
`failure_token_index`, `reason` and `elapsed_s`. On success the records are
returned in `plan.attempt_history`; on failure they are attached to
`diagnostic.details["attempt_history"]`, including the interrupted attempt.

## Tests

`tests/test_layout.py` (26 tests) covers:

- one placement per token on circle, cat and code; placements stay in bounds,
  on allowed cells, non-overlapping and strictly ordered;
- protected blanks for tokens that cannot join, including two identifiers;
- bounded growth until the tokens fit, with failed and successful records;
- exhausted attempts and the canvas size limit, both raising `LAYOUT_LIMIT`;
- end-to-end render plus geometry check for base and grown plans;
- cancellation in the join checker, the stage timeout, the shared deadline
  across retries, the stage budget enforced during mask generation, and the
  elapsed time including packing;
- contiguous-run reset after a separator;
- the realized scale after rounded height;
- the fragmented 178x32 CODE mask flowing tokens across many short spans;
- a token wider than every base span getting a large enough start via the
  estimate, succeeding on the first attempt without small retries;
- an out-of-limit estimate still trying an in-limit canvas (4x8, 24
  semicolons) and succeeding instead of raising `LAYOUT_LIMIT`;
- the column-cap rounding boundary (4x8 base, max_columns=9) backing off
  from a 5x10 over-limit mask to the in-limit 4x8 mask;
- an empty base mask raising structured `INVALID_SHAPE` with the history
  instead of a `ZeroDivisionError`;
- a token that can never fit raising `LAYOUT_LIMIT` with the full history.

## Known limits

- Placement is greedy in reading order; it does not search for a globally
  optimal packing, so a different ordering could in principle use fewer cells.
- A token wider than the largest span the canvas can provide cannot be placed
  and always fails with `LAYOUT_LIMIT`; growth cannot split a token.
- The engine only records placements; it cannot raise coverage itself, which is
  a consequence of the mask geometry and is completed by D's comment filling.
