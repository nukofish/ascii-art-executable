# Part C completion checks

Code under test is the C layout engine. This report covers two rounds and keeps
the historical baseline separate from the actually tested implementation, so
the `Commit` column names the real change rather than the base.

## Baseline and tested implementation

- **Historical baseline:** main `90ce252`, the state after #37 was reverted by
  #38 (the estimate did not exist there). It is used only as the comparison
  base and is not the change under test.
- **Estimate work (merged):** commits `423c939` (canvas clamp) and `1976f93`
  (real-dimension verification), opened as PR #40 and merged into main via
  `ce45ce`. They implement the v1.5 P0 initial size estimation, including the
  row-cap and column-cap boundaries.
- **This round (open, not merged):** branch `layout-empty-mask-guard`, based on
  upstream/main `fb6628f`, adding the empty-base-mask guard (P2). The public
  `contracts.py` signatures are unchanged.

Test date is 12 November 2026 in Asia/Hong_Kong.

## Environment and workspace state

Environment is Python 3.13.16, pytest 9.2.0 on Windows 11 (AMD64). libclang is
not installed on this machine, so the Clang-dependent source tests cannot run
locally; they report `DEPENDENCY_UNAVAILABLE` and are validated by the CI
(libclang 18.1.1). The C-owned `tests/test_layout.py` does not depend on
libclang and runs fully here. See `C_environment.json`.

At test time the layout change was committed on the branch and the working tree
was otherwise clean (`git status` reported only the branch's own changes before
commit; no unrelated file was modified).

The full suite on this machine is `112 failed, 196 passed, 31 skipped`. The
112 failing tests are the same environment set as the baseline (missing
libclang, Windows symlink privilege, CRLF), confirmed by an empty
`Compare-Object` diff; no new regression. The new passing test is the
empty-mask regression.

## The implemented decisions

A scale-1 base mask is built first. From it the engine measures the longest
fillable span `U` and the total fillable cells `A`; from the tokens it takes
the longest token `L` and the total token width `T`. It estimates
`s_est = max(1, initial_scale, L/U, sqrt(T/(eta*A)))` (`eta = 0.75`).

A continuous canvas clamp gives an upper bound, but the builder rounds the
height to an integer and derives the width from that discrete height. The
candidate mask is therefore built and its real dimensions are verified,
backing off row by row until it is in-limit, and the helper returns the
verified start height (an int, at least the base height). A base mask with no
fillable cell raises a structured `INVALID_SHAPE` before the width/area
divisions, rather than a bare `ZeroDivisionError`.

| Tested change | Input | Command | Expected | Actual | Evidence | Status |
| --- | --- | --- | --- | --- | --- | --- |
| 423c939 + 1976f93 (PR #40) | C-owned suite | `python -m pytest tests/test_layout.py -q` | All layout tests pass | 26 passed | C_tests.txt | PASS |
| this branch (base fb6628f) | Empty 4x4 mask, injected builder | `test_empty_base_mask_raises_invalid_shape_with_history` | No division by zero; structured INVALID_SHAPE with empty history | INVALID_SHAPE, stage layout, history () | C_tests.txt | PASS |
| 423c939 (PR #40) | 4x8 canvas, 24 semicolons | `test_out_of_limit_estimate_still_tries_an_in_limit_canvas` | Estimate wants 5 rows but is verified/clamped to scale 1; tokens fit in 4 rows | 1 attempt, h=4, 24 placements | C_tests.txt | PASS |
| 1976f93 (PR #40) | 4x8 base, max_columns=9, 24 semicolons | `test_column_cap_rounding_still_tries_an_in_limit_canvas` | Continuous clamp (9/8=1.125) rounds to a 5x10 over-limit mask; back off to the in-limit 4x8 mask | 1 attempt, h=4, w=8, 24 placements | C_tests.txt | PASS |
| 423c939 (PR #40) | Width-12 token, circle h=4 | `test_longest_token_gets_a_large_enough_start_via_estimate` | Width estimate (L/U=1.5) moves first attempt to h=6 | 1 attempt, h=6, 12-cell span, geometry PASS | C_tests.txt | PASS |
| 423c939 (PR #40) | Width-801 token, limits 800x600 | `test_long_token_that_never_fits_raises_layout_limit_with_history` | Verified in-limit mask (h=400), packing fails, then growth exceeds canvas | LAYOUT_LIMIT, packing record (tok 0) + canvas record (tok None) | C_tests.txt | PASS |
| 423c939 (PR #40) | Width-10 token, fixed 5-wide fake builder | `test_exhausted_attempts_raise_layout_limit_with_history` | Token never fits, all attempts exhausted | 3 failed attempts, all point at token 0 | C_tests.txt | PASS |
| 423c939 (PR #40) | 60 tokens, circle h=6 | `test_growth_retries_until_the_tokens_fit` | Growth by 1.25, bounded, records failures then success | bounded attempts, last record success | C_tests.txt | PASS |
| 423c939 (PR #40) | 200 tokens, max_columns=10 | `test_canvas_size_limit_raises_layout_limit` | Growth rejected at the column limit | LAYOUT_LIMIT, "canvas limits" reason | C_tests.txt | PASS |
| 423c939 (PR #40) | Join checker sets the cancel event | `test_cancellation_in_join_checker_stops_layout` | Packing stops on cancellation | CANCELLED | C_tests.txt | PASS |
| 423c939 (PR #40) | Slow checker, layout_timeout_s=0.05 | `test_layout_stage_timeout_raises_layout_timeout` | Stage timeout reported with history | LAYOUT_TIMEOUT with history | C_tests.txt | PASS |
| 423c939 (PR #40) | Fake builder, 2s stage vs 100s pipeline | `test_mask_building_respects_layout_stage_budget` | Budget enforced during base mask generation | Stops at 2s, not 10s, history key present | C_tests.txt | PASS |
| 423c939 (PR #40) | 1200 width-1 tokens, CODE 178x32 | `test_code_mask_packs_tokens_across_many_short_spans` | Reach fragmented rows and flow across spans | All 1200 placed; tokens occupy multi-span rows | C_tests.txt | PASS |
| 423c939 (PR #40) | initial_scale=1.01, base 32 | `test_actual_scale_reflects_rounded_height` | Scale from rounded height | 33/32 = 1.03125 | C_tests.txt | PASS |

## Coverage of the assigned checks

| Assigned item | Where verified | Status |
| --- | --- | --- |
| Empty-base-mask guard (P2) | empty-mask regression test | PASS |
| Initial size estimate (start height) | width-12 estimate; growth/timeout tests | PASS |
| Canvas clamping (the #37 row-cap regression) | 4x8 in-limit regression test; width-801 test | PASS |
| Column-cap rounding boundary | max_columns=9 column regression test | PASS |
| Long tokens | width-12 estimate; width-801 impossible-canvas test | PASS |
| Multi-span layout | CODE 178x32 short-span test; cat multi-span geometry | PASS |
| Automatic growth (1.25, max 12) | growth and exhausted-attempt tests | PASS |
| Size limits (max_columns=800, max_rows=600) | canvas limit and width-801 tests | PASS |
| Timeout (layout_timeout_s) | stage timeout and shared-deadline tests | PASS |
| Cancellation (cancel_event) | join-checker cancellation test | PASS |
| Attempt history | success and failure histories asserted in every case | PASS |

## Known limits

- Packing is greedy in reading order, not globally optimal.
- The estimate never starts below the base height (32 rows); it cannot shrink
  the canvas for very short code.
- A token wider than the largest span the canvas can provide cannot be split
  and always fails with `LAYOUT_LIMIT`.
- The local machine lacks libclang; the Clang-dependent suite is confirmed by
  CI rather than on this machine.
