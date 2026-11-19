# Part E completion checklist

The evidence was captured on a clean checkout of main at
`b38b92bb7af902a898a5e616f70cce2e191f3c98`. The runner used macOS arm64,
Python 3.12.10, Apple Clang 21.0.0, libclang 18.1.1, and pytest 9.2.0.
[E_evidence.json](e_verify/E_evidence.json) records the measured results and
environment.

| Commit | Input | Command | Expected | Actual | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `b38b92b` | `max2`, `min2`, `clamp`, `absdiff`, `gcd`, `sum_to_n` × circle, cat, CODE at h32 | [Fixed acceptance](#fixed-acceptance) | 18 outputs pass token, geometry, compile and behavior checks. Eight comparisons per output. | All four checks passed for 18/18 outputs. **144/144** comparisons in 6.58 s. Six original and 18 rendered executable builds, plus 18 rendered object builds. | [Fixed matrix](e_verify/E_evidence.json) | PASS |
| `b38b92b` | Geometry of all 18 fixed outputs | [Fixed acceptance](#fixed-acceptance) | Zero out-of-bounds and hole leakage cells. Total coverage ≥ 85% and each cat ear ≥ 70%. | Zero out-of-bounds and hole leakage cells in all 18 outputs. Coverage 98.86–99.90%, minimum cat-ear coverage 89.15%. | [Geometry metrics](e_verify/E_evidence.json) | PASS |
| `b38b92b` | Cat masks at h32, h64 and h128 with B's reference fixtures | [Fixed acceptance](#fixed-acceptance) | The three masks preserve the eye and nose holes and meet the area, centroid and ear-gap tolerances. | 1×, 2× and 4× all passed. Combined report has `passed=true`. | [Cat scales](e_verify/E_evidence.json) | PASS |
| `b38b92b` | `max2` as ordinary source, h32 circle | [Behavior skip cases](#behavior-skip-cases) | No fixture selection. Behavior is skipped with `NO_FIXTURE`. | 64 × 32, token/geometry/compile PASS, behavior `NO_FIXTURE`, zero comparisons. | [Ordinary-source result](e_verify/E_evidence.json) | NOT_RUN |
| `b38b92b` | Built-in `max2`, h240 circle | [Behavior skip cases](#behavior-skip-cases) | Canvas exceeds 100,000 cells. Behavior is skipped with `OUTPUT_TOO_LARGE`. | 480 × 240 = 115,200 cells, token/geometry/compile PASS, behavior `OUTPUT_TOO_LARGE`, zero comparisons. | [Oversized result](e_verify/E_evidence.json) | NOT_RUN |
| `b38b92b` | Full repository test suite | `python -m pytest -q -p no:cacheprovider` | All tests pass. | 284 passed in 22.41 s. | [Test result](e_verify/E_evidence.json) | PASS |

In the two skip rows, **Status** refers to the behavior check. Both skip
reasons matched the expected policy, and neither run contributes comparisons
to the fixed-size matrix. The size policy uses the full canvas width × height.

## Fixed acceptance

Run from the repository root with the pinned dependencies. The command
produces 18 C files and a detailed `report.json` in a fresh directory.

```sh
run_dir=$(mktemp -d)
python -m scripts.run_verification --output-dir "$run_dir/fixed"
python -m codeart.environment
```

Check `behavior_comparisons`, each case's `verification.geometry_metrics`,
and `cat_scales` in the JSON. The `passed` field combines the fixed matrix
and the cat scale checks.

## Behavior skip cases

Both requests use the same built-in source bytes. Only the second request
selects the fixture. It uses the Python API to request a canvas beyond the
CLI's scale range while retaining the default behavior size limit.

```sh
python - <<'PY'
from codeart.contracts import GenerationRequest, LayoutOptions, ShapeSpec
from codeart.pipeline import generate
from codeart.verification_fixtures import select_builtin

selection = select_builtin("max2")
for rows, fixture in ((32, None), (240, selection)):
    result = generate(GenerationRequest(
        selection.fixture.source, ShapeSpec("circle"), fixtures=fixture,
        layout_options=LayoutOptions(base_height_rows=rows, max_attempts=1),
    ))
    mask, report = result.plan.mask, result.verification
    print(mask.width, mask.height, report.token_status.value,
          report.geometry_status.value, report.compile_status.value,
          report.behavior_status.value, report.skip_reasons["behavior"],
          report.behavior_cases_compared)
PY
```

## v1.5 exact cat-hole tolerances

E has used B's `boundary_cells` at each height since [#48](https://github.com/nukofish/ascii-art-executable/pull/48).
The old allowance was `max(0.02 × area, 4 × sqrt(area), 2)` using the
h32 hole area times the square of the scale. Values are in cells.

| Cat scale | Old allowance per eye | Exact allowance per eye | Old nose allowance | Exact nose allowance |
| --- | ---: | ---: | ---: | ---: |
| 1× (h32) | 26.23 | 31 | 12.65 | 14 |
| 2× (h64) | 52.46 | 63 | 25.30 | 30 |
| 4× (h128) | 104.92 | 125 | 50.60 | 62 |

The #48 run at `25650bc` passed 18/18 fixed outputs, 144/144 behavior
comparisons, and all three cat scales. The #58 verification below used the
same exact allowances with its updated cat mask.

## v1.5 budget and coverage decision

Item 12 retained the then-current limits after measurement. The frozen
fixed-fixture thresholds are **85% total** and **70% for each cat ear**.
The measured baseline kept 5 s for input analysis and layout each, 5 s
for output lexing and each compiler invocation, and 2 s per behavior
executable's batch of eight inputs. The generation budget was 30 s and the
fixed regression budget 180 s overall, with at most 30 s per case. Behavior
comparisons ran for matching fixtures on canvases of at most 100,000 cells.

[#59](https://github.com/nukofish/ascii-art-executable/pull/59) later raised
the default layout-stage limit to 60 s. The default 30 s generation budget
still caps layout, including on #58. The fixed-fixture thresholds above
still apply.

A clean checkout of `b66cbc94ac769e23fd8b1c84fd8e8e2e4f5cfe17` (includes
[#42](https://github.com/nukofish/ascii-art-executable/pull/42)) ran on
macOS arm64 with Python 3.12.10, Apple Clang 21.0.0, libclang 18.1.1, and
pytest 9.2.0.

- The [fixed acceptance command](#fixed-acceptance) returned `passed=true`,
  with 18/18 outputs, 144/144 comparisons, and cat masks at 1×, 2×, and 4×
  passing. The matrix took 5.29 s and its slowest generation took 0.55 s.
  Total coverage was 98.86–99.90%, and the lowest single-ear coverage was
  89.15%. The largest per-case compile and behavior phase totals were
  0.095 s and 0.332 s. These phase totals cover multiple builds or executions
  when applicable.
- The long-token CLI example grew from the default height of 32 to 41 rows
  through the initial estimator and passed token, geometry, and compilation.
  See the [82 × 41 output](scaled/case_auto_grow_circle_h41_s1.28125.c) and its
  [JSON report](scaled/case_auto_grow_circle_h41_s1.28125.json).
  The [oversized fixture probe](#behavior-skip-cases)
  confirmed that at 480 × 240 those checks pass and behavior reports
  `NOT_RUN (OUTPUT_TOO_LARGE)` with zero comparisons.
- The boundary regression command below passed 50 tests. The timeout and
  cancellation cases use shortened limits or injected work to check stop
  behavior and diagnostics. The real Web file-mode test generates the
  extracted function through HTTP. The separate orchestration tests verify
  that delayed prepass work reduces the budget passed to generation and
  that cancellation during prepass stops the job before generation.

```sh
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
python -m pytest -q tests/test_app.py tests/test_prepass.py tests/test_web_app.py \
  tests/test_layout.py::test_layout_stage_timeout_raises_layout_timeout \
  tests/test_layout.py::test_layout_timeout_is_shared_across_retries \
  tests/test_pipeline.py::test_expired_budget_prevents_next_stage \
  tests/test_source.py::test_analysis_stops_and_reaps_worker \
  tests/test_verify.py::test_large_canvas_still_compiles \
  tests/test_verify.py::test_compile_stage_timeout_and_global_deadline \
  tests/test_verify.py::test_wrapper_build_failure_skips_behavior \
  tests/test_verify.py::test_behavior_timeout_marks_case_index \
  tests/test_verify.py::test_running_process_group_is_cancelled \
  tests/test_cli.py::test_cli_prepass_timeout_keeps_common_failure_report --tb=short
```

F signed off on item 12 and the fixed-fixture thresholds of **85% overall**
and **70% for each cat ear**. Web function-extraction prepass and generation share one
**30 s** budget and the same cancellation signal. In Chromium, cancelling
during prepass ended the job as `CANCELLED` with all four checks
`NOT_RUN (CANCELLED)`. Web **Find functions** and CLI `--file` prepass have
separate budgets. [F browser acceptance and sign-off in #53](https://github.com/nukofish/ascii-art-executable/pull/53)

### Whole-program budgets and coverage

Item 12 was frozen for single-function input. Whole-program mode (#58) keeps
the same limits and adds no new ones:

- Analysis uses the 5 s input-analysis limit. It covers the Clang
  resource-directory lookup (and the SDK lookup on macOS) as well as parsing.
- Layout is configured for 60 s (#59) but stays capped by the 30 s generation
  budget. The 244- and 364-line regressions pass with an explicit 5 s layout
  budget.
- Verification lexes the artwork once (5 s), preprocesses the original and the
  generated program (each one compiler invocation of at most 5 s), then
  compiles and links the output (5 s). Custom code is never executed, so no
  behavior budget applies.

The **85% total** and **70% per cat ear** thresholds remain acceptance
thresholds for the fixed-fixture matrix. They are not checked on each
generation in either mode, and whole-program output reports coverage without
a floor. The [whole-program samples](whole_program/README.md) measured
90.20–95.61% for cat and circle with every cat ear at or above 88.2%, but
79.01–88.71% for the CODE shape. A program's own token mix, not the mask,
decides how densely its ink fills that shape, so a fixed floor there would
reject valid programs. Geometry still requires zero out-of-bounds and zero
hole-leakage cells.

## Whole-program verification sign-off

E reviewed [#58](https://github.com/nukofish/ascii-art-executable/pull/58) at
`2ac4f95a4e97cacda662c7243008a43fcd935cfd` with a clean checkout. Whole-program
input extends the v1.5 single-function scope and follows E's four-check
contract. `token` covers both the raw artwork tokens and the preprocessed
complete source, `geometry` covers the canvas, and `compile` builds the complete
output and links it when `main` is present. The two token comparisons share
one status and report the first mismatch. Details are in the
[verification guide](../modules/verify.md#checks-and-report-fields).

| Web input | Token | Geometry | Compile | Behavior |
| --- | --- | --- | --- | --- |
| UTF-8 program with a macro and `main` | PASS | PASS | PASS (linked) | NOT_RUN (NO_FIXTURE) |
| Translation unit without `main` | PASS | PASS | PASS (object) | NOT_RUN (NO_FIXTURE) |
| `main` calls a declared function with no definition | PASS | PASS | FAIL (link) | NOT_RUN (COMPILE_NOT_PASS) |
| Relocating a macro redefinition changes the expansion | FAIL | NOT_RUN (TOKEN_NOT_PASS) | NOT_RUN (TOKEN_NOT_PASS) | NOT_RUN (TOKEN_NOT_PASS) |

Since `e314ebd`, an `#undef` after program code, and a conditional block that
contains code after program code, are rejected during analysis with
`UNSUPPORTED_SOURCE` at their own line, so they no longer reach the token
check. A relocated `#define` that changes the expansion still fails the token
check as in the last row. `__LINE__`, the clock macros and the spacing copied
by stringizing are neutralised in the preprocessed comparison; see the
[verification guide](../modules/verify.md#checks-and-report-fields).

The local HTTP probes checked that downloaded JSON preserved each status and
reason. They recorded zero behavior comparisons and zero calls to the
execution entry point for custom code.

On macOS arm64 with Python 3.12.10, Apple Clang 21.0.0 and libclang bindings
18.1.1, `python -m scripts.run_verification --output-dir "$run_dir/fixed"`
with a fresh run directory produced `passed=true`, 18/18 fixed outputs,
144/144 comparisons, and PASS at cat 1×, 2×, and 4×. The run took 6.82 s.
Overall coverage was 99.05–99.90%, with a minimum of 91.67% per cat ear.
The following targeted suite passed 72 tests.

```sh
NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost \
python -m pytest -q -p no:cacheprovider tests/test_program.py tests/test_verify.py \
  tests/test_verification_cli.py tests/test_app.py tests/test_web_app.py --tb=short
```
