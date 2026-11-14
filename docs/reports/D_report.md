# Part D — Comment filling and source output

## What it does

`codeart/fill.py` implements `render_source(model, plan, fill_options, *, ctx)`.
It writes every token at the cells chosen by C, keeps holes and protected
blanks empty, and fills the remaining fillable cells with the two comment
forms accepted by E. It never moves, resizes or rewrites a token and never
changes the layout.

## How it works

- Tokens are written from `LayoutPlan.placements`; `allowed == False` cells,
  `protected_blanks` and other tokens' cells are never overwritten.
- A free gap is one contiguous run inside a single span. A block comment
  (`/*=...=*/`, at least four cells) keeps one blank cell next to a real
  token on each touching side; gaps shorter than four cells stay blank.
- A line comment (`//=...=`) is used only at the tail of the last span of a
  row, only when no real token follows, and it must reach the span end.
  `FillOptions(allow_line_comments=False)` disables this form.
- Every row ends with LF. Coverage is computed with the same definitions as
  E: denominator = allowed cells, numerator = non-space characters; token,
  block-comment and line-comment contributions are reported separately in
  `comment_cells`.

## Tests

`tests/test_fill.py` has 33 tests; `tests/test_generate_d_reports.py` adds 3
generator regressions (existing-directory refusal, status aggregation, partial
result archiving).

- fake-mask boundary tests: internal and tail gaps 1–10, real `/` adjacency,
  line comment before a later token, cat multi-span rows, disabled line
  comments, string literal with an internal space;
- six real A → C → D cases (`div`, `gcd` × circle/cat/code): re-lex through
  the shared profile, `check_geometry`, hole-ink and division-adjacency
  checks, then `clang -std=c11 -pedantic-errors -c`.

`scripts/generate_d_reports.py` regenerates 18 ordinary-input cases
(6 functions × 3 shapes) and their logs, manifest and check table. It requires
a fresh `--output-dir`, refuses to overwrite an existing directory, never
deletes other members' evidence, and exits non-zero when a required check is
not PASS or only a partial result is available. Evidence records the full
HEAD, branch, dirty flag and base commit.

## Results

Snapshot: HEAD `fb6628f43df6261dc1ddeabc70cd8754b0d4fd1b`, branch
`part-d/evidence-final` (dirty: `no`), base `main@fb6628f`.

| metric | result |
|---|---|
| token / geometry / compile | 18/18 PASS |
| behavior | 18/18 `NOT_RUN (NO_FIXTURE)` (ordinary input) |
| coverage | 0.9886 – 0.9990 |
| token coverage | 0.0082 – 0.0555 |
| block-comment coverage | 0.0000 – 0.5123 |
| line-comment coverage | 0.4687 – 0.9764 |
| hole ink | 0 |
| shortest block comment | 5 cells (grammar minimum 4) |
| line comments | every `//` reaches the row end |
| layout attempts / scale | 1 / 1 |
| independent `clang -c` | rc 0 in 18/18 |

## Known limitations

- One comment per gap; a gap is not split into several comments.
- Line comments are single-line; no backslash continuation.
- Ordinary input has no behavior fixture, so behavior is `NOT_RUN`.
- D does not choose sizes or retries; automatic scaling belongs to C/E.
- Coverage is a layout consequence: D cannot raise it by breaking the
  boundary rules.

## Artifacts

- `docs/reports/part-d/2026-11-14_final/case_<function>_<shape>_h<rows>_s<scale>.c` and `.log`
- `docs/reports/part-d/2026-11-14_final/D_manifest.csv`
- `docs/reports/part-d/2026-11-14_final/D_cases.md`
- `docs/reports/D_checklist.md` (summary)
