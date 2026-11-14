# Module B (v2) — shape masks (`codeart/shapes.py`)

[中文](shapes.zh-CN.md)

B no longer downsamples photos: it **generates the pattern**. Given a shape
request it returns a `Mask` — the grid of cells the layout engine (C) may fill —
plus the geometry features the verifier (F) measures. B never emits source code.

## Interface

```python
from codeart import FontMetrics, ShapeSpec, SizeRequest, build_mask, geometry_metrics

mask = build_mask(
    ShapeSpec(kind="cat"),          # "circle" | "cat" | "code"
    SizeRequest(height_rows=32),    # C decides the row count
    FontMetrics(cell_aspect=0.5),   # fixed constant for the project
)
```

`build_mask(shape_spec, size_request, font_metrics, *, ctx=None) -> Mask`

| type | fields |
|---|---|
| `FontMetrics` | `font_id: str \| None = None`, `cell_width_px: float \| None = None`, `cell_height_px: float \| None = None`; `cell_aspect` is a **derived property** (see below) |
| `SizeRequest` | `height_rows: int` |
| `ShapeSpec` | `kind: str`, `text: str \| None`, `inner_radius: float \| None` |
| `Mask` | `kind`, `width`, `height`, `allowed[row][col]`, `spans[row]`, `font_metrics`, `features`, `inner_radius`; `scale` is a **derived property** |

`ctx` is an optional cancellation context: if it exposes `raise_if_cancelled()`
or `check()`, that hook is called once per row (duck typing — no dependency on
F's `contracts.py`).

### Cell metrics and `cell_aspect`

`FontMetrics` stores the font identity and the optional cell pixel size; the
ratio C uses is **derived** from them and is never a second authority:

| construction | `cell_aspect` |
|---|---|
| `FontMetrics()` | `0.5` (project default) |
| `FontMetrics(0.5)` / `FontMetrics(cell_aspect=0.5)` | `0.5` — the same metrics as `FontMetrics()` |
| `FontMetrics(font_id="mono", cell_width_px=8, cell_height_px=16)` | `8 / 16 = 0.5` |

`cell_aspect` stays the first parameter, so `FontMetrics(0.5)` keeps working;
`font_id` and the cell pixel size are keyword-only. The project fixes the ratio
at `CELL_ASPECT_DEFAULT = 0.5`, so both an explicit `cell_aspect` and a pixel
pair are accepted only within `CELL_ASPECT_TOLERANCE = 1e-9` of it; anything
else raises `INVALID_SHAPE` when the metrics are constructed.

### Sizing

C owns the height. B derives the width from the physical aspect ratio `r`:

```
columns = ceil(height_rows × r / cell_aspect)
```

With `cell_aspect = 0.5`, a shape with `r = 1.0` at 32 rows is 64 columns wide
(physical width `64 × 0.5 = 32` equals the height).

`Mask.scale` is not stored: it is a read-only property equal to `height / 2`,
the number of rows per shape unit (the shape is normalised to `v ∈ [-1, 1]`).
It is **derived, not authoritative** — `width` and `height` are the only size
authorities on `Mask`, so the two can never disagree.

| kind | r | 32 rows | 64 rows |
|---|---|---|---|
| `circle` | 1.0 | 64×32 | 128×64 |
| `cat` | 1.0 | 64×32 | 128×64 |
| `code` | 25/9 ≈ 2.778 | 178×32 | 356×64 |

## Shapes

### `circle`

Solid disk: a cell is allowed when `u² + v² ≤ 1`, where `(u, v)` is the cell
centre normalised so that `v ∈ [-1, 1]` and `u` is scaled by `cell_aspect`.
The bounding box is exactly the requested rectangle, so its physical aspect
ratio is 1.0.

### `cat`

Cat head: an ellipse (`rx = 0.95`, `ry = 0.80`, centre slightly below the
middle), two triangular ears whose tips reach the top edge, two elliptical eye
holes and one nose hole. Holes punch through the silhouette, so the head stays a
single connected fillable region with three interior holes.

### `code`

A solid rectangle with the word **CODE** hollowed out, using a built-in 5×7
bitmap font (one unit of letter spacing, one unit of margin on every side so
strokes never touch the mask border). `text` defaults to `"CODE"`; any other
value raises `INVALID_SHAPE`. The glyph bitmaps live in `_GLYPHS` in
`codeart/shapes.py` and are plain ASCII art, so they are easy to tweak.

## `spans` convention

`spans[row]` lists every maximal run of allowed cells on that row as half-open
`(start, end)` pairs:

- ordered by `start`, non-overlapping, `0 ≤ start < end ≤ width`;
- holes split a row into several spans (every `cat` and `code` mask has rows with
  two or more spans — e.g. the rows through the cat's eyes);
- a fully allowed row is `((0, width),)`; a fully blocked row is `()`.

Rebuilding a row from its spans must reproduce `allowed[row]` exactly; the test
suite asserts this for every shape at 32 and 64 rows.

`tests/fixtures/shapes/{circle,cat,code}_32.json` are fixed snapshots of
`allowed` + `spans` at 32 rows (≈12 KB in total) and are checked in the
regression test.

## `features`

Named geometry, each a set of 0-based `(row, col)` cells:

| key | meaning |
|---|---|
| `eye_left`, `eye_right` | eye holes (cells that are **not** allowed) |
| `nose` | nose hole |
| `ear_left`, `ear_right` | ear silhouettes (allowed cells) |
| `eyes`, `ears` | unions of the two sides |
| `code_strokes` | glyph cells hollowed out of the `code` rectangle |

Circle masks have no features (`{}`). Eye and nose sets describe the holes, so
their cells are always `allowed == False`.

## `geometry_metrics(mask)`

Helper for the verifier (E). Returns:

```
kind, cols, rows, cell_aspect,
bbox: {cols, rows, ratio},                 # ratio = cols*cell_aspect/rows
allowed_cells, spans_total, rows_with_multiple_spans,
eye_cells: {left, right}, nose_cells,
ear_gap_rows,                             # dip between the ear tips, in rows
boundary_cells: {eye_left, eye_right, nose},  # v1.5 outline-crossed cell counts
holes: [{cells, centroid: {row, col}}],   # interior holes only
code_stroke_cells
```

### Ear notch (`ear_gap_rows`, plan v1.5)

`ear_gap_rows` is the dip between the two ear peaks. The v1.5 plan
("统一验收清单——耳峰凹陷定义") replaced the v1.4 rule — global peak row plus
the single column between the rasterised apex centroids — with:

1. **two independent peaks**: the left peak is the highest fillable row of
   `features["ear_left"]`, the right peak the same for `ear_right`, so a
   trimmed tip on one ear cannot hide the other peak;
2. **a fixed central window**: the notch bottom is the lowest upper-boundary
   cell inside the columns `[start, end)` with
   `end - start = max(NOTCH_MIN_WINDOW_CELLS, round(width * NOTCH_WINDOW_FRACTION))`
   centred on `width * NOTCH_CENTER_FRACTION`;
3. **the lower peak is the reference**: depth is
   `notch_bottom - max(left_peak, right_peak)`, so a raised (trimmed) ear can
   only shrink the dip, never be compensated by the other ear.

Public constants (importable from `codeart` and `codeart.shapes`):

| constant | default | meaning |
|---|---|---|
| `NOTCH_CENTER_FRACTION` | `0.5` | window centre as a fraction of the mask width |
| `NOTCH_WINDOW_FRACTION` | `0.02` | window width as a fraction of the mask width |
| `NOTCH_MIN_WINDOW_CELLS` | `3` | the window is never narrower than three columns |

The window is deliberately narrow: the notch floor is flat only over the
central band (at 128 rows the cells at the notch row span `|u| <= 0.026`, about
2.6 % of the width), so a wider window would sample the head's shoulders and
add rows purely from resolution instead of measuring the dip.
`ear_notch_rows(mask, *, center_fraction=..., window_fraction=...)` exposes the
same computation for callers that want to vary the window.

v1.5 regression case: remove three cells from the h32 left ear tip. The peaks
become rows 1 (left) and 0 (right), the central upper boundary is row 5, and
the depth is `5 - 1 = 4`. v1.4 returned `0` there because the left ear owned no
cell on the global peak row; the asymmetric case is pinned by
`test_ear_notch_survives_a_trimmed_ear_tip`. Symmetric masks keep the v1.4
values (5 / 10 / 15 / 20 at h32/h64/h96/h128), because the window stays on the
flat notch floor.

### Hole boundary cells (`boundary_cells`, plan v1.5)

`hole_boundary_cells(mask, hole)` returns the number of grid cells the
**analytic outline** of `hole` (`eye_left`, `eye_right`, `nose`) crosses — the
exact quantisation bound of a centre-sampled hole, not an area formula.

Algorithm:

- the hole is the ellipse in `HOLE_ELLIPSES` (`(cx, cy, rx, ry)`, in the same
  normalised `(u, v)` space the mask is rasterised in);
- the grid comes from the mask: cell edges are at
  `u = (col - width/2) * 2*aspect/rows` and `v = row * 2/rows - 1`;
- a cell counts when the outline enters it through one of its four sides: each
  side is a segment and is tested for an ellipse intersection by solving
  `A t² + B t + C = 0` for `t ∈ [0, 1]` — no corner sampling, no tolerance;
- a cell whose four corners are all inside (or all outside) is *not* counted,
  even when the outline grazes it, because the outline does not pass through a
  side.

Measured values (also stored per hole in `metrics_h*.json`):

| hole | h32 | h64 | h96 | h128 |
|---|---|---|---|---|
| eye (each) | 31 | 63 | 95 | 125 |
| nose | 14 | 30 | 46 | 62 |

Part E approximated this bound with `max(0.02*A, 4*sqrt(A), 2)`. The exact
count is what that approximation stood in for: for a hole rasterised by
cell-centre sampling the area error *is* the number of outline-crossed cells,
so it can be used directly as the per-hole tolerance. The formula stays valid
as a fallback for callers that only know the area.

## Scaled reference data for verification

`tests/fixtures/shapes/metrics_h{32,64,96,128}.json` are generated snapshots for
Part E. Each file covers all three shapes at one height (`circle`, `cat`, and
`code` with `text="CODE"`). Regenerate them with:

```bash
python scripts/gen_shape_metrics.py
```

`h128` is the height used by Part E's acceptance set (h32/h64/h128); `h96` is
kept for continuity.

The generator calls `build_mask` + `geometry_metrics` for every shape/height;
no value is hand-written. It is deterministic — two runs produce byte-identical
files — and `tests/test_shape_metrics.py` checks that the committed fixtures
still match the implementation.

Top-level fields:

| field | meaning |
|---|---|
| `schema_version` | `1` |
| `cell_aspect` | `0.5`, the project-wide cell width / cell height |
| `height_rows` | row count shared by all shapes in this file |
| `generated_by` | generator path, `scripts/gen_shape_metrics.py` |
| `tolerance` | tolerances used by E (see below) |
| `shapes` | `circle`, `cat`, `code` → per-shape record |
| `scaling_expectation` | prose note plus the reference height (`32`) used by the scaling formulas |

Per-shape record:

| field | meaning |
|---|---|
| `cols`, `rows` | mask size (columns depend on the shape's physical aspect ratio) |
| `bbox_ratio` | occupied bounding-box ratio: `bbox_cols * cell_aspect / bbox_rows` |
| `allowed_cells` | number of fillable cells |
| `spans_total` | total number of maximal allowed runs over all rows |
| `rows_with_multiple_spans` | rows split by at least one hole |
| `features` | named eye/nose holes only; `{}` for `circle` and `code` |
| `hole_count` | number of named hole features: `3` for `cat`, `0` otherwise |
| `ear_gap_rows` | cat only: rows between the lower ear peak and the fixed-window notch bottom; `null` otherwise |

Each feature is:

| field | meaning |
|---|---|
| `cells` | number of cells in the feature (the `A_ref` below) |
| `bbox` | inclusive `[min_row, min_col, max_row, max_col]` |
| `centroid` | `[row, col]` in **cell-centre** coordinates (`index + 0.5`) |
| `boundary_cells` | v1.5: grid cells crossed by the hole's analytic outline (exact area-quantisation bound) |

### Tolerance contract

For a feature measured at 32 rows with area `A_ref`:

```
A_expected(h) = A_ref * (h / 32) ** 2
area_limit(h) = max(area_rel * A_expected(h),
                    area_perimeter_factor * sqrt(A_expected(h)),
                    area_min_cells)
area_ok      = abs(cells(h) - A_expected(h)) <= area_limit(h)
centroid_ok  = abs(centroid(h)[axis] - centroid(32)[axis] * h / 32) <= centroid_abs_cells
```

The area term is **perimeter-scaled** on purpose. Reference cells are sampled at
cell centres, so a hole's measured count differs from its ideal continuous area
by the cells its outline cuts through; that error is proportional to the hole's
**perimeter**, and for area `A` the perimeter grows like `sqrt(A)`, not like a
constant. One fixed absolute number is therefore wrong at both ends of the
range: `20` cells allowed a 300% error on the 10-cell nose at 32 rows, while at
96 rows the eye's 16-cell quantisation drift already consumed 80% of the same
budget and left almost no headroom for a real regression.

Measured against the 32-row reference (`area_perimeter_factor = 4.0`,
`area_rel = 0.02`, `area_min_cells = 2`):

| feature | h | `A_ref` | `A_expected` | measured | `area_limit` | verdict |
|---|---|---|---|---|---|---|
| eye | 32 | 43 | 43 | 43 | 26.2 | pass (exact reference) |
| eye | 64 | 43 | 172 | 163 | 52.5 | pass (9-cell drift) |
| eye | 96 | 43 | 387 | 371 | 78.7 | pass (16-cell drift) |
| nose | 32 | 10 | 10 | 10 | 12.6 | pass (exact reference) |
| nose | 64 | 10 | 40 | 34 | 25.3 | pass (6-cell drift) |
| nose | 96 | 10 | 90 | 74 | 37.9 | pass (16-cell drift) |

The factor 4.0 reflects the boundary ring of a centre-sampled rasterised disc,
which is roughly `4 * sqrt(A)` cells: it admits the observed drift with a modest
margin while still rejecting a reference that is off by 50%. For large features
the 2% relative term takes over; `area_min_cells = 2` keeps degenerate one-cell
holes from having a zero budget. `bbox_ratio` is dimensionless and must not
drift with height: the four files may differ by at most
`bbox_ratio_abs = 0.05`.

`centroid` is stored in cell-centre coordinates on purpose: raw cell indices
carry a `-0.5` bias that does not scale with `h`, while `(row + 0.5)` does.
`hole_count` counts named eye/nose holes only; it is not
`len(geometry_metrics()["holes"])`, which can include incidental one-cell
quantisation components at some resolutions.

### E assertion example

```python
doc = json.loads((FIXTURES / "metrics_h32.json").read_text())
ref, tol = doc["shapes"]["cat"]["features"]["eye_left"], doc["tolerance"]
expected = ref["cells"] * (96 / 32) ** 2
limit = max(tol["area_rel"] * expected,
            tol["area_perimeter_factor"] * expected ** 0.5,
            tol["area_min_cells"])
got = len(build_mask(ShapeSpec("cat"), SizeRequest(96), FontMetrics()).features["eye_left"])
assert abs(got - expected) <= limit  # 371 vs 387, limit 78.7
```

`tests/test_shape_metrics.py` additionally checks feature-key equality at every
height, quadratic area scaling, linear centroid scaling, the
height-invariant `bbox_ratio`, and byte-for-byte generator idempotence. Two
negative controls guard the contract from the other side: a reference eye
inflated by 1.5x must fail the scaling invariant, and the h96 eye losing 100
cells must exceed `area_limit`.

## Acceptance targets (measured at 32 rows)

| metric | target | measured |
|---|---|---|
| eye cells | each ≥ 4 | 43 / 43 |
| nose cells | ≥ 2 | 10 |
| ear dip between peaks | ≥ 2 rows | 5 (unchanged by the v1.5 window) |
| circle bbox ratio | 1.0 ± 0.05 | 1.000 |
| determinism | two calls identical | yes (dataclass equality) |
| scaling 32 → 64 | eye area ×~4, geometry preserved | 43 → 163 (×3.79), nose 10 → 34, dip 5 → 10 |

## Errors

`build_mask` raises the shared `PipelineError` from `codeart.contracts`, always
with `stage="shape"` and a `Diagnostic(code, stage, message, location=...)`:

```python
from codeart import ErrorCode, PipelineError

try:
    build_mask(ShapeSpec("circle"), SizeRequest(0), FontMetrics())
except PipelineError as exc:
    assert exc.diagnostic.code is ErrorCode.INVALID_SIZE
    assert exc.diagnostic.stage == "shape"
    assert exc.diagnostic.location == "SizeRequest.height_rows"
```

`ShapeError` is kept as a synonym of `PipelineError`
(`ShapeError is PipelineError`), so `except ShapeError` and `except StageError`
keep catching B's failures; `exc.code` still returns the plain string code for
compatibility. `diagnostic.location` names the request field or produced
artifact the failure refers to — shape failures have no source line.

| code | when |
|---|---|
| `INVALID_SHAPE` | unknown `kind`; `text != "CODE"`; `inner_radius is not None` (rings are not supported yet); a `cell_aspect` or cell pixel pair that is not `0.5`; a mask with no fillable cell |
| `INVALID_SIZE` | `height_rows` not a positive int; a malformed cell metric (`cell_aspect`, `cell_width_px` or `cell_height_px` non-finite or `≤ 0`, or a width without a height) |

### Empty-mask guard

`build_mask` validates the grid before returning it. If no cell is allowed —
which also means every row has zero spans — it raises
`PipelineError(INVALID_SHAPE)` with `location="Mask.allowed"` instead of
handing C a canvas it could never fill.

## Running the tests

```bash
python -m pytest tests/test_shapes.py -q     # 44 passed
```

The suite covers all three shapes at 32 and 64 rows, span reconstruction,
holes-not-allowed, multi-span rows, the acceptance metrics above, determinism,
the derived `cell_aspect`/`scale` contracts, the `INVALID_SHAPE` /
`INVALID_SIZE` error codes, the empty-mask guard, the `ctx` duck-typing hook, the v1.5 asymmetric-ear case, the exact
hole-boundary-cell counts and the fixture regression.
