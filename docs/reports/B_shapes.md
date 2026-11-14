# Part B — completion checklist and evidence

- **Evidence commit:** `4b8b5b8b29e761e5e808b5dfc69acb4b4d004f94` (`origin/main`);
  the code under test is that tree, and everything added on top is documentation
- **Branch:** `part-b-checklist` (the fork already has a branch named `part-b`,
  so the nested ref `part-b/checklist` cannot be created on it)
- **Uncommitted changes:** none outside `docs/reports/` — `git status --porcelain`
  only ever lists the files this PR adds, and `git status --porcelain
  tests/fixtures/shapes` is empty after both generator runs
- **Host:** macOS 27.0.1 arm64 · CPython 3.13.5 · pytest 9.2.0
- **cell_aspect:** `0.5` (project-wide constant, not configurable per call)
- **libclang:** not required — B is pure Python
- **Evidence:** [B_tests.txt](b_shapes/B_tests.txt) ·
  [B_checks.txt](b_shapes/B_checks.txt) ·
  [B_environment.json](b_shapes/B_environment.json) ·
  [B_checks.py](b_shapes/B_checks.py) ·
  [run_b_evidence.sh](b_shapes/run_b_evidence.sh)

**Scope.** B turns a `ShapeSpec` + `SizeRequest` into a `Mask`: the allowed-cell
grid, its row spans and the named holes, for `circle`, `cat` and `code`. B does
not choose the height, lay out tokens, fill text or judge behaviour — those are
C (scale decision), D (fill), E (verification) and F (operation).

## Completion checklist

Every row below was executed on the commit above. `Actual` values are copied
from [B_checks.txt](b_shapes/B_checks.txt) and [B_tests.txt](b_shapes/B_tests.txt);
nothing in this table is estimated.

| Check | Commit | Input | Command | Expected | Actual | Evidence | Status |
|---|---|---|---|---|---|---|---|
| a) `build_mask` produces all three patterns at h32 | `4b8b5b8` | `circle`, `cat`, `code` at `height_rows=32` | `python docs/reports/b_shapes/B_checks.py` | a mask with `rows=32`, non-empty `allowed`, `inner_radius=None` | `circle` 64×32 (1612 cells, 32 spans); `cat` 64×32 (1316, 50); `code` 178×32 (4154, 172); `inner_radius=None` | B_checks.txt §a | PASS |
| b) `spans` rebuild `allowed` cell for cell | `4b8b5b8` | 3 shapes × h32/h64 | `python docs/reports/b_shapes/B_checks.py`; `pytest tests/test_shapes.py -q` | rebuilt grid equals `allowed` everywhere; spans sorted, disjoint, in bounds | 6/6 combinations `identical=True` (1612 / 6440 / 1316 / 5284 / 4154 / 16224 cells); no overlap or out-of-range span | B_checks.txt §b; `test_spans_rebuild_allowed_exactly` | PASS |
| c) Cat holes and ear gap meet the acceptance minimums | `4b8b5b8` | `cat` at h32 (ladder to h128 reported below) | `python docs/reports/b_shapes/B_checks.py`; `pytest tests/test_shapes.py -q` | eye ≥ 4 cells each, nose ≥ 2, `ear_gap_rows` ≥ 2, 3 named holes | h32: eyes 43 / 43, nose 10, `ear_gap_rows` 5; h64: 163 / 163, 34, 10; 3 named holes at every height | B_checks.txt §c; `test_cat_features_meet_acceptance` | PASS |
| d) Circle physical bounding-box ratio is 1.0 ± 0.05 | `4b8b5b8` | `circle` at h32/h64/h96/h128 | `python docs/reports/b_shapes/B_checks.py` | `abs(bbox.ratio − 1.0) ≤ 0.05` | `ratio = 1.000000` at all four heights; `abs_error = 0.000000` | B_checks.txt §d; `test_circle_bbox_ratio` | PASS |
| e) Two identical requests produce identical output | `4b8b5b8` | 3 shapes at h32, built twice | `python docs/reports/b_shapes/B_checks.py`; `pytest tests/test_shapes.py -q` | `mask` and metrics compare equal; spans digest stable | `mask_equal=True`, `metrics_equal=True` for all 3 kinds; spans sha256 `df727ccf…` (circle), `aa510eb5…` (cat), `d122796e…` (code) both times | B_checks.txt §e; `test_determinism` | PASS |
| f) Invalid requests are rejected with the documented codes | `4b8b5b8` | `inner_radius=0.5`; `code text="HELLO"`; `height_rows=0`; `height_rows=-5` | `python docs/reports/b_shapes/B_checks.py`; `pytest tests/test_shapes.py -q` | `INVALID_SHAPE`, `INVALID_SHAPE`, `INVALID_SIZE`, `INVALID_SIZE` | `INVALID_SHAPE` / `INVALID_SHAPE` / `INVALID_SIZE` / `INVALID_SIZE` (no silent clamping) | B_checks.txt §f; `test_inner_radius_is_rejected`, `test_code_text_must_be_code`, `test_invalid_height_rows` | PASS |
| g) Fixtures match the implementation and regeneration is idempotent | `4b8b5b8` | `tests/fixtures/shapes/metrics_h{32,64,96,128}.json` | `python scripts/gen_shape_metrics.py` twice, `sha256sum`, `python -m pytest tests/test_shapes.py tests/test_shape_metrics.py -q` | 4/4 fixtures equal a fresh build; both runs byte-identical; 48 tests pass | 4/4 `identical=True`; the four sha256 values are unchanged across baseline, run 1 and run 2; `48 passed in 1.06s` | B_tests.txt; B_checks.txt §g | PASS |
| h) Geometry scales with height | `4b8b5b8` | `cat` h32 → h64/h96/h128 | `python docs/reports/b_shapes/B_checks.py`; `pytest tests/test_shape_metrics.py -q` | area ≈ `A32·(h/32)²` within `max(0.02·e, 4√e, 2)`; centroid ≈ `c32·h/32` within 1.0 cell; `bbox_ratio` spread ≤ 0.05 | eye delta −9 / −16 / −30 against expected 172 / 387 / 688, limits 52.5 / 78.7 / 104.9; largest centroid delta 0.39 cell; `bbox_ratio` spread 0.048651 (cat), 0.000000 (circle, code) | B_checks.txt §h; `test_feature_areas_scale_with_height_squared` | PASS |
| Full repository suite | `4b8b5b8` | whole repo | `python -m pytest -q` | green | not run: outside B's scope, and the E/F suites need libclang, which is not importable in this venv | B_environment.json (`libclang_required`) | NOT_RUN |

## Key numbers

Shape size at every fixture height (`cols × rows`, then allowed cells):

| Height | circle | cat | code |
|---|---|---|---|
| 32 | 64×32 · 1612 | 64×32 · 1316 | 178×32 · 4154 |
| 64 | 128×64 · 6440 | 128×64 · 5284 | 356×64 · 16224 |
| 96 | 192×96 · 14500 | 192×96 · 11898 | 534×96 · 36904 |
| 128 | 256×128 · 25760 | 256×128 · 21138 | 712×128 · 64592 |

Cat holes (`eye_left` / `eye_right`, `nose`, `ear_gap_rows`):

| Height | eyes | nose | ear_gap_rows |
|---|---|---|---|
| 32 | 43 / 43 | 10 | 5 |
| 64 | 163 / 163 | 34 | 10 |
| 96 | 371 / 371 | 74 | 15 |
| 128 | 658 / 658 | 138 | 20 |

- Row spans (h32 / h64): circle 32 / 64, cat 50 / 99, code 172 / 350.
- Rows with more than one span (h32 / h64): circle 0 / 0, cat 13 / 26, code 24 / 50.
- `bbox_ratio`: circle 1.0, cat 0.967742 / 1.016393 / 1.010870 / 1.016260, code 2.78125 at every height.
- Fixture sha256 (identical before the first generator run, after it and after
  the second): `7f301e8d0753…` (h32), `eb1fb2434cca…` (h64),
  `679b1fe07a15…` (h96), `b31df543643a…` (h128); full values in
  [B_tests.txt](b_shapes/B_tests.txt).

### What the −9 / −16 / −30 means

The mask is rasterised by cell-centre sampling: a cell is allowed when its
centre falls inside the analytic ellipse. The sampled area is therefore always
an inscribed approximation, so the error is biased negative and grows with the
number of boundary cells — i.e. with the perimeter, which grows like `√A`.
Measured eye area against `43·(h/32)²`: 163 (−9, 5.2 %), 371 (−16, 4.1 %),
658 (−30, 4.4 %). The absolute drift rises monotonically with height while the
relative drift falls, which is exactly the signature of quantisation at a finer
grid, not of a geometry bug. The nose follows the same pattern (34 / 74 / 138
against 40 / 90 / 160). This is why the shipped tolerance is
`max(0.02·expected, 4·√expected, 2)` and not a fixed amount: 52.5 / 78.7 / 104.9
cells at the three heights, wide enough for the real drift and still narrow
enough that the two counterexample tests in `tests/test_shape_metrics.py` fail
an inflated reference (1.5× eye) and a 100-cell h96 shrink.

## B → E handoff

- E reads `tests/fixtures/shapes/metrics_h32.json`, `metrics_h64.json` and
  `metrics_h128.json` for scales 1, 2 and 4. **h96 is kept as a scale-3
  regression fixture** so the older three-height set keeps working.
- `base_area` is always the h32 value:
  `base_area = shapes["cat"]["features"]["eye_left"]["cells"]` (43), and the
  expectation at another height is `area_at_scale = base_area × scale²` with
  `scale = h / 32`.
- `center` uses the centroid of the **current** height. B stores `centroid` in
  cell-centre coordinates (`index + 0.5`), so E subtracts `0.5` to obtain the
  cell-index mean it compares against its own measurement; without that
  correction every centroid is off by half a cell.
- `ear_gap_rows` is read from the current height (5 / 10 / 15 / 20 at
  h32/h64/h96/h128), not scaled from h32; it is an integer row count.
- Every fixture carries the `tolerance` object E asserts against:
  `area_rel = 0.02`, `area_perimeter_factor = 4.0`, `area_min_cells = 2`,
  `centroid_abs_cells = 1.0`, `bbox_ratio_abs = 0.05`.
- Only named `eye_left`, `eye_right` and `nose` features are published.
  `geometry_metrics()["holes"]` counts every interior blank component, so at
  h96 it reports 5 (3 named plus 2 incidental one-cell artefacts) while
  `hole_count` stays 3. E must use the named features, not the raw hole count.

## Known limits

- `code` accepts the literal `"CODE"` only (built-in 5×7 glyphs, hollow
  strokes); any other `text` raises `INVALID_SHAPE`.
- `inner_radius` is part of `ShapeSpec` but must be `None`; ring shapes are a
  later increment and currently raise `INVALID_SHAPE`.
- `FontMetrics.cell_aspect` is fixed at `0.5`, so a 32-row circle is 64 columns
  wide and physical width equals height.
- B trusts `SizeRequest`; it never grows or shrinks the height. Empty or
  degenerate sizes are the caller's error, surfaced as `INVALID_SIZE`.
- The table above verifies B's own contract only. Fill, layout, behaviour and
  the builtin compile matrix belong to D/E/F and are `NOT_RUN` here.

## Reproduce

```sh
git clone https://github.com/nukofish/ascii-art-executable /tmp/bchk
cd /tmp/bchk && git checkout 4b8b5b8
python3 -m venv /tmp/bchkvenv
/tmp/bchkvenv/bin/python -m pip install -q pytest

# tests + two generator runs + sha256 comparison -> B_tests.txt
PY=/tmp/bchkvenv/bin/python bash docs/reports/b_shapes/run_b_evidence.sh

# per-check numbers -> B_checks.txt
/tmp/bchkvenv/bin/python docs/reports/b_shapes/B_checks.py
```

## v1.5 更新（2026-11-14，复查第 9、10 项）

分支 `part-b/v15-ear-notch-and-boundary-cells`，base `origin/main@dc689f2`。只改 B 的范围：
`codeart/shapes.py`、`codeart/__init__.py`（B 的公开导出）、`scripts/gen_shape_metrics.py`、
`tests/fixtures/shapes/metrics_h*.json`、`tests/test_shapes.py`、`tests/test_shape_metrics.py`、
`docs/modules/shapes*.md`、本报告。`codeart/verification_regression.py` **未改**（E 的消费端，
由 E 另开 PR 切换）。

### 9. 耳峰凹陷按计划定义重算

**旧规则（v1.4）**：取两耳全局最高行 `peak_row = min(r for r, _ in ears)`，再取两个耳尖在
`peak_row` 上的列质心中点作为正中列，凹陷 = `top[mid] - peak_row`。左耳顶端缺 3 格时，左耳
在全局最高行没有顶点，`left_apex` 为空，凹陷直接返回 0。

**新规则（v1.5《统一验收清单——耳峰凹陷定义》）**，实现为
`codeart.shapes.ear_notch_rows(mask, *, center_fraction=..., window_fraction=...)`：

1. 左右耳**分别**求峰：`min(row)` over `ear_left` / `ear_right`；
2. 在**固定中央窗口** `[start, end)` 内取上边界最低行（每列第一条可填行，取最大行号）；
   窗口宽 `max(NOTCH_MIN_WINDOW_CELLS, round(width * NOTCH_WINDOW_FRACTION))`，以
   `width * NOTCH_CENTER_FRACTION` 居中；
3. 深度 = `中央最低行 - max(左峰, 右峰)`，即相对**较低**的那只耳峰。

公开常量：`NOTCH_CENTER_FRACTION = 0.5`、`NOTCH_WINDOW_FRACTION = 0.02`、
`NOTCH_MIN_WINDOW_CELLS = 3`（`codeart` 与 `codeart.shapes` 均可导入）。`geometry_metrics`
的字段名仍是 `ear_gap_rows`，值按新定义计算。

**不对称复现用例**（h32，左耳顶端去掉 3 格：
`tests/test_shapes.py::test_ear_notch_survives_a_trimmed_ear_tip`）：

| 项 | 行号 |
|---|---|
| 左耳峰 | 1 |
| 右耳峰 | 0 |
| 中央窗口上边界最低 | 5 |
| 新 `ear_gap_rows` | `5 - max(1, 0)` = **4** |
| 旧 `ear_gap_rows` | **0**（回归） |

**对称模板新旧值**：

| 高度 | 旧 `ear_gap_rows` | 新 `ear_gap_rows` | 差异 | fixture |
|---|---|---|---|---|
| 32 | 5 | 5 | 0 | `metrics_h32.json` 中不变 |
| 64 | 10 | 10 | 0 | `metrics_h64.json` 中不变 |
| 96 | 15 | 15 | 0 | `metrics_h96.json` 中不变 |
| 128 | 20 | 20 | 0 | `metrics_h128.json` 中不变 |

窗口为什么取 2%（至少 3 列）：凹陷底部只在中央一小段是平的——128 行时，与凹陷底同一行的格
只覆盖 `|u| <= 0.026`，约为宽度的 2.6%。窗口再宽就会量到头顶的**斜坡**而不是凹陷：按
`window_fraction = 0.2`（±10% 宽）试算，四档会变成 **5 / 11 / 16 / 22**，多出来的行完全
来自分辨率，而且会让 E 现有的 `ear_gap_rows == 20` 参考断言（`tests/test_verification_cli.py`）
失败。因此窗口上限取 0.02，并加 `NOTCH_MIN_WINDOW_CELLS = 3` 保证最小高度下也不是单列；
对称模板的新值与旧值一致，不对称用例由「分别求峰 + 取较低峰」修复。

### 10. 孔洞边界格 fixture（`boundary_cells`）

`codeart.shapes.hole_boundary_cells(mask, hole)`：孔洞用 `HOLE_ELLIPSES` 里的解析椭圆
（`(cx, cy, rx, ry)`，与 mask 同一归一化 `(u, v)` 空间），网格边在
`u = (col - width/2) * 2*aspect/rows`、`v = row * 2/rows - 1`；**轮廓从格的四条边之一穿过**
才计数（四条边各作线段，解 `A t² + B t + C = 0` 求 `t ∈ [0, 1]` 的交点），四角全在内/全在外
的格不计。不是面积近似，也没有角点采样容差。

`scripts/gen_shape_metrics.py` 为每个孔洞额外输出 `boundary_cells`（整数），
`geometry_metrics()["boundary_cells"]` 也带同一组值。

| 孔洞 | h32 | h64 | h96 | h128 |
|---|---|---|---|---|
| eye_left / eye_right（每只） | 31 | 63 | 95 | 125 |
| nose | 14 | 30 | 46 | 62 |

**与复查文档对照值核对**（32/64/128）：

| 孔洞 | 文档 | 实测 | 结论 |
|---|---|---|---|
| 眼 32 | 31 | 31 | 一致 |
| 眼 64 | 63 | 63 | 一致 |
| 眼 128 | 125 | 125 | 一致 |
| 鼻 32 | 14 | 14 | 一致 |
| 鼻 64 | 30 | 30 | 一致 |
| 鼻 128 | 62 | 62 | 一致 |

六项全部一致，没有需要 E 裁决的口径差异。h96 文档没给对照值，实测眼 95、鼻 46。

**与旧近似公式的关系**：E 之前用 `max(0.02*A, 4*sqrt(A), 2)` 估计面积容差。格中心采样的孔洞
面积误差**就是**轮廓穿过的格数，因此 `boundary_cells` 是那条公式想表达的精确值；公式保留为
只有面积信息时的兜底。E 尚未切换：`codeart/verification_regression.py` 仍用公式
（h128 眼 `boundary_cells` 容差 104.919016 不变），本 PR 不碰它。

### 实测命令与结果

```sh
/tmp/bv15venv/bin/python -m pytest -q
# 351 passed in 31.65s        （基线 338，新增 13 个用例）

/tmp/bv15venv/bin/python -m scripts.run_verification --output-dir /tmp/bv15-evidence-v15
# PASS fixed matrix (144/144 comparisons) | /tmp/bv15-evidence-v15/report.json
# Scaled cat: 1x PASS, 2x PASS, 4x PASS

/tmp/bv15venv/bin/python scripts/gen_shape_metrics.py   # 连跑两次
sha256sum tests/fixtures/shapes/metrics_h*.json
# 两次运行的四个 sha256 完全一致，见下表
```

| fixture | sha256（修改后，两次生成一致） |
|---|---|
| `metrics_h32.json` | `2112e66b27d60602573e6b7bd5e07493cb2f5180820c46712463f4a7cdcdd258` |
| `metrics_h64.json` | `98b008bcd7fdc324d2d659d7aa3b09da7c6742535a91ae401303641e336d4b12` |
| `metrics_h96.json` | `158bce92bee52b6ac834399eff34488f08ec8b7aebd7bcc8ead8fee61318e5c6` |
| `metrics_h128.json` | `0d19fc541e6adaee47a4db7a9ff06a9f760dbf636f313ab1a5d29845511fa9d9` |
