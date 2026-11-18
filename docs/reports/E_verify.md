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

## v1.5 budget and coverage decision

Retain the existing limits. Coverage applies to the fixed fixtures at
**85% total** and **70% for each cat ear**. Keep 5 s for input
analysis and 5 s for layout, 5 s for output lexing and 5 s per compiler
invocation, and 2 s per behavior executable's batch of eight inputs. The
generation budget stays at 30 s and the fixed regression budget at 180 s
overall, with at most 30 s per case. Run behavior comparisons for matching
fixtures on canvases of at most 100,000 cells.

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
and **70% for each cat ear**. Web file-mode prepass and generation share one
**30 s** budget and the same cancellation signal. In Chromium, cancelling
during prepass ended the job as `CANCELLED` with all four checks
`NOT_RUN (CANCELLED)`. Web **Find functions** and CLI `--file` prepass have
separate budgets. [F browser acceptance and sign-off in #53](https://github.com/nukofish/ascii-art-executable/pull/53)
