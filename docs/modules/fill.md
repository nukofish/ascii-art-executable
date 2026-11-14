# Module D — comment filling and source output (`codeart/fill.py`)

D writes the tokens that C placed and fills every remaining fillable cell with
the two comment forms E accepts. It never moves, resizes, reorders or rewrites
a token, and it never writes into a hole, a `protected_blank` or another
token's cells.

## Interface

```python
from codeart.fill import render_source

rendered = render_source(
    model,        # SourceModel: tokens with index, spelling, width
    plan,         # LayoutPlan: mask, placements, protected_blanks
    fill_options, # FillOptions(allow_line_comments=True)
    ctx=ctx,      # RunContext; ctx.check() once per row
)
```

| type | fields used |
|---|---|
| `SourceModel` | `tokens` (`index`, `spelling`, `width`) |
| `LayoutPlan` | `mask` (`width`, `height`, `allowed`, `spans`), `placements`, `protected_blanks` |
| `FillOptions` | `allow_line_comments` |
| `RenderedCode` | `source_text`, `position_map`, `coverage`, `token_coverage`, `comment_coverage`, `comment_cells` |

`position_map[token_index] = (row, col)` is copied from `plan.placements`.

## Canvas rules

1. Each placement writes `token.spelling` at `(row, col)`; text cell count is
   `token.width == len(token.spelling)`, so spaces inside a string literal are
   part of the token and are never treated as gaps.
2. `mask.allowed == False` cells stay blank (holes).
3. `protected_blanks` stay blank (mandatory separators chosen by C).
4. A free gap is one contiguous run inside a single span. Gaps never cross a
   hole or another span.
5. Every output row ends with LF, including the last row. Trailing spaces are
   trimmed; a token's trailing spaces are kept.

## Comment grammar

Only two forms are emitted; E's geometry checker matches the same grammar.

### Block comments (interior gaps)

```
/*====...====*/          # at least "/**/" (4 cells), body is only "="
```

- If the gap touches a real token on a side, reserve one blank cell on that
  side; the 4-cell minimum applies to the comment itself, not the blanks.
- After the boundary blanks, a gap needs at least 4 free cells, otherwise it
  stays blank (1–3 leftover cells are allowed to stay blank).
- One block comment fills the whole available run.

### Line comments (row tail only)

```
//====...====            # "//" plus "=" body, at least 2 cells
```

- Only at the tail of the **last span of a row** and only when no real token
  follows on that row.
- The comment must extend to the span end; otherwise a later allowed cell
  would remain after it and E reports `line_comment_tail`.
- After the boundary blank at least 2 free cells are required; a 1-cell tail
  stays blank.
- `FillOptions(allow_line_comments=False)` disables this form completely.

## Coverage

The denominator is the number of `allowed == True` cells; only non-space
characters inside allowed cells count as ink. Token-internal spaces and
boundary blanks are not ink.

```
coverage         = (token ink + block comment cells + line comment cells) / allowed
token_coverage   = token ink / allowed
comment_coverage = (block + line) / allowed
comment_cells    = {"block": block cells, "line": line cells}
```

`comment_cells` counts the comment delimiters too. The values must match E's
re-computation exactly (`geometry_metrics["coverage"]` etc.).

## Errors

A placement that does not match its token, leaves the canvas, covers a
non-fillable cell or overlaps another token makes the plan unusable. D raises
`StageError(Diagnostic(ErrorCode.INTERNAL_ERROR, "render", ...))`; the pipeline
keeps the earlier stages' artifacts. D does not report verification results —
that is E's job.

## Tests

`tests/test_fill.py` covers:

- circle row with three tokens (first acceptance case), geometry check passes;
- internal gap lengths 1–10 and tail gap lengths 1–10;
- real `/` before a comment (boundary blank keeps the division operator);
- a line comment before a later token is refused (block comment instead);
- cat multi-span row: first span block comment, middle span block comment,
  last span line comment;
- `allow_line_comments=False`;
- string literal with an internal space (`"a b"` is one 5-cell token);
- a real A → C → D regression for `div` and `gcd` on all three shapes:
  `source.analyze_source` → `layout.fit_layout` → `render_source`, then the
  rendered source is re-lexed through the shared profile, checked with
  `check_geometry`, inspected for hole ink / division adjacency / line tails,
  and compiled with `clang -std=c11 -pedantic-errors -c`.

## Real-layout evidence

`scripts/generate_d_reports.py` writes the 18 ordinary-input cases
(6 functions × 3 shapes) into a **fresh** `--output-dir`. It refuses an existing
directory, never deletes other members' evidence, and exits non-zero when a
required check is not PASS, diagnostics are present, or only a partial result
is available. Evidence records the full HEAD, branch, dirty flag and base.

- `case_<function>_<shape>_h<rows>_s<scale>.c` plus a matching `.log`;
- `D_manifest.csv` with statuses, coverage split, comment counts, attempts,
  scale, duration and the independent compile result;
- `D_cases.md`, the run-local table; `D_checklist.md` summarizes the DoD.

Measured at HEAD `fb6628f43df6261dc1ddeabc70cd8754b0d4fd1b`
(branch `part-d/evidence-final`, dirty: no, base `main@fb6628f`):

| metric | result |
|---|---|
| token / geometry / compile | 18/18 PASS |
| behavior | 18/18 `NOT_RUN (NO_FIXTURE)` as expected for ordinary input |
| coverage | 0.9886 – 0.9990 |
| token coverage | 0.0082 – 0.0555 |
| block-comment coverage | 0.0000 – 0.5123 |
| line-comment coverage | 0.4687 – 0.9764 |
| hole ink | 0 in every cat/code case |
| block comments | minimum length 5 (grammar minimum 4) |
| line comments | every `//` reaches the end of its row |
| layout attempts / scale | 1 / 1 (these inputs fit at the base height) |
| independent `clang -c` | rc 0 in 18/18 cases |

## Known limits

- One comment per gap; a gap is not split into several comments.
- Line comments are single-line by construction; no backslash continuation.
- Coverage is a layout consequence: if C leaves small spans, D cannot raise it
  without breaking the boundary rules.
- Ordinary input has no behavior fixture, so `behavior_status` is `NOT_RUN`
  with reason `NO_FIXTURE`; the 144 comparisons belong to E's builtin matrix.
- D reads the real `LayoutPlan` from C; it does not choose sizes, scales or
  retry counts. Automatic scaling is exercised by C/E, not by these cases.
