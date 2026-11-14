# Part D — completion checklist

- **Evidence HEAD:** `fb6628f43df6261dc1ddeabc70cd8754b0d4fd1b`
- **Branch:** `part-d/evidence-final` (dirty: `no`)
- **Base:** `main@fb6628f`
- **Host:** macOS-27.2.1-arm64-arm-64bit
- **Python:** 3.11.16
- **clang:** Apple clang 21.0.0
- **Artifacts:** `docs/reports/part-d/2026-11-14_final/case_<function>_<shape>_h<rows>_s<scale>.c`
- **Case table:** `docs/reports/part-d/2026-11-14_final/D_cases.md`
- **Manifest:** `docs/reports/part-d/2026-11-14_final/D_manifest.csv`
- **Generator:** `python scripts/generate_d_reports.py --output-dir docs/reports/part-d/2026-11-14_final`

The generator refuses an existing output directory, never deletes other
members' files, and exits non-zero when any required check is not PASS or when
only a partial result is available.

## DoD table

| Case | Commit | Input | Command | Expected | Actual | Evidence | Conclusion |
|---|---|---|---|---|---|---|---|
| Fake-layout boundary tests | `fb6628f` | masks/tokens built in the test | `python -m pytest tests/test_fill.py -q` | all boundary tests pass | 33 passed | `tests/test_fill.py` | PASS |
| Real A→C→D regression | `fb6628f` | `div`, `gcd` × circle/cat/code | `python -m pytest tests/test_fill.py -q` | 6 real-layout cases pass | 6 passed | `tests/test_fill.py::test_real_layout_relexes_geometry_and_compiles` | PASS |
| 18 ordinary-input outputs | `fb6628f` | `max2`, `min2`, `clamp`, `absdiff`, `gcd`, `sum_to_n` × 3 shapes | `python scripts/generate_d_reports.py --output-dir docs/reports/part-d/2026-11-14_final` | 18/18 token/geometry/compile PASS | 18/18 PASS; behavior 18/18 `NOT_RUN (NO_FIXTURE)` | `docs/reports/part-d/2026-11-14_final/D_cases.md` | PASS |
| Division adjacency | `fb6628f` | `sum_to_n` (`(n + 1) / 2`), `div` | generator + `tests/test_fill.py` | no `//` or `/*` immediately after a real `/` | no violation found | `case_sum_to_n_*_h32_s1.c`, real-layout test | PASS |
| Short gaps | `fb6628f` | internal gaps 1–10, tail gaps 1–10 | `python -m pytest tests/test_fill.py -q` | gaps <4 stay blank; `/**/` at 4 | assertions pass | `tests/test_fill.py` gap tests | PASS |
| Line-end comments | `fb6628f` | all 18 outputs | generator | every `//` reaches the row end | `line_tail_ok = YES` in 18/18 | `D_cases.md` | PASS |
| Hole blanks | `fb6628f` | cat eyes/nose, hollow CODE strokes | generator | hole ink = 0 | 0 in 18/18 | `D_manifest.csv` | PASS |
| Coverage split | `fb6628f` | all 18 outputs | generator | token / block / line contributions reported | three columns populated in 18/18 | `D_manifest.csv` | PASS |
| Independent compile | `fb6628f` | all 18 outputs | generator | `clang -std=c11 -pedantic-errors -c` rc 0 | rc 0 in 18/18 | `D_cases.md` | PASS |
| Generator refusal / partial result | `fb6628f` | existing directory; cancelled-after-render result | `python -m pytest tests/test_generate_d_reports.py -q` | refuse overwrite; archive partial and exit non-zero | 3 passed | `tests/test_generate_d_reports.py` | PASS |

## Full test run

`python -m pytest -q` on this snapshot: **338 passed**, including **33** in
`tests/test_fill.py` and **3** in `tests/test_generate_d_reports.py`.

## Key numbers

- coverage: **0.9886 – 0.9990**
- token coverage: **0.0082 – 0.0555**
- block-comment coverage: **0.0000 – 0.5123**
- line-comment coverage: **0.4687 – 0.9764**
- hole ink: **0**
- shortest block comment: **5** cells
- line comments: **18/18** reach the row end
- layout attempts / scale: **1 / 1**
- independent `clang -c`: **18/18 rc 0**

## Known limits

- Ordinary input has no behavior fixture, so behavior is `NOT_RUN`; the 144
  comparisons belong to E's builtin-fixture matrix.
- These 18 inputs all fit at the base height (`attempts = 1`, `scale = 1`);
  automatic scaling is exercised by C/E, not by this table.
- Coverage is split into token / block-comment / line-comment contributions
  in `D_manifest.csv`; the denominator is the number of allowed cells.
- D never changes the layout; a poor coverage value is a layout consequence,
  not something D may fix by filling outside the rules.
- The evidence directory is a fresh run directory; future scaled or repeated
  runs must use a new `--output-dir`.
