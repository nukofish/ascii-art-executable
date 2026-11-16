# Module E — verification and regression

[中文](verify.zh-CN.md)

`codeart.verify.verify(model, plan, rendered, fixtures, profile, *, ctx)`
takes A's source model, C's layout with B's mask, D's generated source, and
F's run context. It returns a `VerificationReport`.
`codeart.pipeline.generate()` uses the production components by default.
Tests can inject substitutes through the pipeline dependencies.

## Integration contract

- `model` provides `original_source`, `function_name`, and the effective
  tokens in source order. Each token has an `index`, `kind`, `spelling`,
  `width`, `source_line`, and `source_column`.
- `plan.mask` is B's `Mask`. Each placement carries `token_index`, `row`,
  and `col`. `protected_blanks` holds `(row, col)` pairs.
  `rendered.position_map` maps each token index to its `(row, col)`.
  Grid coordinates are zero-based. Source positions in diagnostics are
  one-based. Generated source uses LF, includes every canvas row and a
  final newline, and may omit trailing spaces.
- A's `prepare_profile()` binds the default raw lexer callback. The pipeline
  passes A's returned profile to E. A custom `lex_source(text, *, ctx)`
  returns tokens with `kind`, `spelling`, `line`, `column`, and
  `is_comment`. It observes the deadline and cancellation signal. To report
  a missing dependency, analysis timeout, cancellation, or pipeline
  timeout, raise `StageError(Diagnostic(...))`. E preserves the diagnostic.
- Ordinary input uses `fixtures=None`. A built-in entry point calls
  `select_builtin(name)` and passes the selection and its `fixture.source`
  to the pipeline. Behavior testing requires the registered selection and
  an exact match against the original source and function name in A's
  model. E adds the test wrapper only to temporary compilation inputs.
- `ctx.deadline` is an absolute monotonic deadline. `ctx.cancel_event` is a
  shared cancellation signal or `None`. Isolated tests can use
  `VerificationContext(monotonic() + 30, event)`.

## Checks and report fields

- **Token.** E lexes the full generated source and compares the effective
  tokens after dropping comments. The first difference gives a zero-based
  index and the original spelling and source position on each side. A side
  that has reached the end is represented by `None`. A token failure leaves
  geometry, compilation, and behavior at `NOT_RUN (TOKEN_NOT_PASS)`. A missing
  lexer or a lexer stage timeout still allows the independent geometry check.
- **Geometry.** E scans the actual characters to check boundaries, holes,
  protected cells, placements, comment fill rules, and D's position and
  cell counts. Coverage divides nonblank characters in fillable cells by
  the number of fillable cells. Spaces inside string literals do not
  contribute to coverage. The report counts ink outside the canvas,
  outside the mask, and in holes. Hole leakage also counts toward the
  out-of-bounds total.
- **Compile.** After the token check passes, E runs an object build using
  `-std=c11 -pedantic-errors` by default, even if geometry fails. When geometry
  passes and the input qualifies for behavior testing, the compile stage also
  builds the original and generated executables with the test wrapper. A build
  failure or compile timeout sets `compile_status=FAIL` and leaves behavior at
  `NOT_RUN (COMPILE_NOT_PASS)`. The diagnostic identifies the failed build.
- **Behavior.** E runs comparisons after the first three checks pass.
  Without a matching fixture, the result is `NOT_RUN (NO_FIXTURE)`. With a
  matching fixture and more than 100,000 canvas cells, it is
  `NOT_RUN (OUTPUT_TOO_LARGE)`.
- **Budgets.** Lexing and compilation default to five seconds each. Each
  behavior executable gets two seconds for all eight inputs. The overall
  deadline bounds every operation. Missing dependencies, cancellation, and
  overall timeout leave unfinished checks at `NOT_RUN`. A compilation or
  execution stage timeout is a `FAIL`. On macOS and Linux, E runs compiler
  and test children in their own process groups and kills and reaps them
  on cancellation or timeout.

F displays the four statuses independently. `diagnostics` holds structured
details, `skip_reasons` maps check names to reasons, and `durations` records
seconds for attempted stages. `compiler` records the actual compiler path,
version, and flags. `behavior_cases_compared` counts completed comparisons.

## Fixed-size acceptance

Run from the repository root. Give each run a fresh directory, and keep
fixed-size evidence separate from automatic growth demonstrations.

```sh
python -m scripts.run_verification --output-dir docs/reports/2026-11-09-pr-review/fixed
```

The command passes all six built-in samples to the production pipeline,
with a height of 32 rows and one layout attempt. A successful run writes
18 files named `case_<function>_<shape>_h32_s1.c` and a `report.json`. The
report records the commit SHA, checkout state, dimensions, source file
references, four statuses, diagnostics, skip reasons, timings, and build
counts. Use a run with `checkout_dirty=false` for formal evidence. The
command refuses an existing output directory to protect earlier evidence.

Exit code 0 means the fixed-size matrix passed. The report preserves any
source files and diagnostics from failed cases. If a case stops before
verification, all four checks are `NOT_RUN` and `generation_diagnostics`
gives the reason. The 144 comparisons count only inputs that ran.

The same command reads B's `metrics_h{32,64,128}.json` files and reports
the 1×, 2×, and 4× cat checks under `cat_scales`. B uses h96 for its 3×
regression. The JSON field `passed` requires the fixed matrix and all three
cat checks to pass. The exit code reflects `fixed_matrix_passed`. A scale
with no reference is `NOT_RUN (MISSING_REFERENCE)`. All scales use h32 for
the base area and tolerance parameters.

Expected eye and nose areas are the h32 counts multiplied by the square
of the scale. The tolerance is the maximum of B's relative term,
perimeter approximation, and minimum cell count. The centroid and ear gap
come from the corresponding height. B stores cell-center coordinates.
The adapter subtracts 0.5 from each axis to obtain E's zero-based cell
indices.

## Isolated tests and regression interface

```sh
python3 -m pytest -q tests/test_shapes.py tests/test_verify.py
```

F can inject the report fixtures in
`tests/fixtures/verification_reports.py`. E's isolated matrix uses real B
masks, test layouts, and a Clang raw lexer adapter. `tests/test_source.py`
also runs 18 production pipeline cases. The acceptance command runs the
whole production matrix in one build session and archives the evidence.

`codeart.verification_regression.run_regression(generate_case)` calls the
adapter as `generate_case(selection, shape_spec, *, ctx)`. The adapter
forwards the selection and cancellation signal, observes the shared
deadline, and returns a `VerificationReport` or `None` if the pipeline
did not reach verification. The budget is 180 seconds overall and at
most 30 seconds per case. The serial build session caches original
executables and object builds and cleans up its temporary files.

`matrix_passed` requires all four checks on all 18 cases, 144 completed
comparisons, six original executable builds, and 18 rendered executable
builds. The default minimum total coverage is 0.85 and each cat ear must
reach 0.70. Callers can load B's fixtures with
`load_cat_references(directory)` and pass the result as `cat_references`.
The keys are 1, 2, and 4. Each reference supplies the base hole areas,
per-scale centers, area tolerances, and ear-gap depth. `passed` requires
both the matrix and all three scales.

## Cross-module changes

- **A and E share process tools.** `codeart.procutil` provides process
  execution, termination, and temporary build sessions. `source.py` uses
  `run_command`, `BuildSession`, and the associated exceptions.
  `_source_lexer.py` calls the public `stop_process` and waits for and reaps
  the child. Changes to these interfaces should run A's source and lexer
  tests and E's timeout and cancellation tests.
- **B, C, and D deliver shared data.** If mask feature names, coordinate
  conventions, placements, or comment counts change, check the shared
  contracts, E's geometry rules, and the fixed-size regression together.
  B supplies the shape references that E checks against the actual masks.
- **F consumes the public report and sample selection.** Run ordinary input
  through `generate()`. For a built-in sample, pass the source and
  selection from `select_builtin(name)` directly to the pipeline. Read
  the four statuses and skip reasons from `VerificationReport`. Use these
  public entry points for cross-module calls. E owns its underscored
  modules and the internal sample build cache.
