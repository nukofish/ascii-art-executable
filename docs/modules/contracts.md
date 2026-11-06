# Shared interfaces for Parts A through F

Import common types from `codeart.contracts`. Use
`codeart.pipeline.generate(request, *, deps=None, cancel_event=None)` to run
the pipeline. The default dependency factory loads the repository modules.
Tests can pass compatible implementations in `PipelineDeps`.

## Module entry points

| Part | File | Interface |
| --- | --- | --- |
| A | `codeart/source.py` | `analyze_source(text, profile, *, ctx) -> SourceModel`<br>`can_join(run_tokens, next_token, profile) -> bool` |
| B | `codeart/shapes.py` | `build_mask(shape_spec, size_request, font_metrics, *, ctx) -> Mask` |
| C | `codeart/layout.py` | `fit_layout(model, shape_spec, options, *, mask_builder, join_checker, ctx) -> LayoutPlan` |
| D | `codeart/fill.py` | `render_source(model, plan, fill_options, *, ctx) -> RenderedCode` |
| E | `codeart/verify.py` | `verify(model, plan, rendered, fixtures, profile, *, ctx) -> VerificationReport` |

## Data passed between modules

- **A to C, D and E.** Keep the input in `SourceModel.original_source` and
  store normalized text separately. Number effective tokens in source order,
  preserve their original spelling and use the spelling length as their
  width. `can_join` takes the entire contiguous token run and one candidate.
  Provide a raw lexer callback `lex_source(text, *, ctx)` that yields
  `LexedToken` values, including comments. A and E share one
  `VerificationProfile`.
- **B to C, E and F.** The contract re-exports B's existing `ShapeSpec`,
  `SizeRequest`, `FontMetrics` and `Mask` classes. The default cell
  width-to-height ratio is 0.5. C requests a height in rows and B computes the
  width. Each row's `spans` lists all half-open fillable intervals
  `[start, end)`. Shape keys are `circle`, `cat` and `code`. The hollow
  text is fixed to `CODE` and `inner_radius` is reserved as `None`.
- **C to D, E and F.** Call the injected `mask_builder` and `join_checker`.
  Pass the same `ctx` to B. Read actual width and height from `plan.mask`
  and the layout multiplier from `plan.actual_scale`. Keep placements in
  token order and track mandatory separator cells in `protected_blanks`.
  Record layout attempts in order in `attempt_history`.
- **D to E and F.** Map each token to its generated position with
  `position_map[token_index] = (row, col)`. Output every canvas row with an
  LF, including the last row. Count visible block and line comment cells
  under the keys `block` and `line` in `comment_cells`. Report coverage as
  a fraction from 0 to 1.
- **E to F.** Report token, geometry, compile and behavior checks separately.
  Each check has status `PASS`, `FAIL` or `NOT_RUN`. Key `skip_reasons` by
  `token`, `geometry`, `compile` and `behavior`. A token mismatch includes
  original and generated locations in `first_diff`. Use `fixtures=None`
  for ordinary input. The built-in sample entry point passes the result of
  E's `select_builtin(name)` with the exact matching source. F forwards the
  selection to E unchanged.
- **Coordinates.** Grid rows, grid columns, span offsets and token indices
  are zero-based. Source lines and columns shown to users are one-based.

## Errors, time budgets and cancellation

Each stage receives the same `RunContext`. Check `ctx.check()` in long
loops and before expensive work. Limit child processes to the smaller of
the remaining stage budget and `ctx.remaining_s()`. Terminate and reap them
when cancelled or timed out. Layout retries share one stage budget.

A, C and D can raise `StageError(Diagnostic(...))` for diagnosed failures.
F maps B's existing `ShapeError` to the shared error codes. E reports
verification failures and skipped checks in its report. F preserves the
plan, rendered code and partial verification report once returned. The
display treats checks without a result as `NOT_RUN`.

E uses the shared report, status and profile types. Existing imports from
`codeart.verify` still work. For token verification, E passes the lexer a
context that supports the shared budget API and limits the deadline to the
smaller of the lexer budget and the overall deadline. The cancellation
signal is shared with the pipeline. Update the shared types and fixtures
together when a module interface changes.
