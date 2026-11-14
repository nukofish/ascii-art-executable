"""Tests for B (v2): shape mask generation (`codeart.shapes`)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from codeart import (  # noqa: E402
    CELL_ASPECT_TOLERANCE,
    NOTCH_CENTER_FRACTION,
    NOTCH_MIN_WINDOW_CELLS,
    NOTCH_WINDOW_FRACTION,
    FontMetrics,
    Mask,
    ShapeError,
    ShapeSpec,
    SizeRequest,
    build_mask,
    ear_notch_rows,
    geometry_metrics,
    hole_boundary_cells,
)
from codeart import shapes  # noqa: E402
from codeart.contracts import ErrorCode, PipelineError, StageError  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "shapes"
KINDS = ("circle", "cat", "code")


def make(kind: str, rows: int = 32, **kwargs):
    return build_mask(ShapeSpec(kind, **kwargs), SizeRequest(rows), FontMetrics())


def allowed_from_spans(width: int, spans) -> list[list[bool]]:
    """Rebuild allowed[][] from spans — the definition used by the renderer."""
    rows = []
    for row_spans in spans:
        row = [False] * width
        for start, end in row_spans:
            assert 0 <= start < end <= width, (start, end, width)
            for col in range(start, end):
                assert not row[col], "spans overlap"
                row[col] = True
        rows.append(row)
    return rows


# --------------------------------------------------------------- structure --

def test_three_shapes_at_two_sizes():
    for kind in KINDS:
        for rows in (32, 64):
            mask = make(kind, rows)
            assert mask.height == rows
            if kind in ("circle", "cat"):
                assert mask.width == math.ceil(rows * 1.0 / 0.5)
            assert len(mask.allowed) == mask.height
            assert all(len(row) == mask.width for row in mask.allowed)
            assert len(mask.spans) == mask.height
            assert mask.inner_radius is None
            assert mask.kind == kind
            assert mask.font_metrics.cell_aspect == 0.5


def test_spans_rebuild_allowed_exactly():
    for kind in KINDS:
        for rows in (32, 64):
            mask = make(kind, rows)
            rebuilt = allowed_from_spans(mask.width, mask.spans)
            assert rebuilt == [list(row) for row in mask.allowed]


def test_spans_are_sorted_and_disjoint():
    for kind in KINDS:
        mask = make(kind, 32)
        for row_spans in mask.spans:
            starts = [s for s, _ in row_spans]
            assert starts == sorted(starts)
            for (s1, e1), (s2, _e2) in zip(row_spans, row_spans[1:]):
                assert e1 <= s2


def test_hole_cells_are_not_allowed():
    cat = make("cat", 32)
    for name in ("eye_left", "eye_right", "nose"):
        for (r, c) in cat.features[name]:
            assert cat.allowed[r][c] is False
    code = make("code", 32)
    assert code.features["code_strokes"]
    for (r, c) in code.features["code_strokes"]:
        assert code.allowed[r][c] is False


def test_some_row_has_multiple_spans():
    for kind in ("cat", "code"):
        mask = make(kind, 32)
        assert any(len(row) >= 2 for row in mask.spans), kind


# ------------------------------------------------------------------- metrics --

def test_cat_features_meet_acceptance():
    for rows in (32, 64):
        mask = make("cat", rows)
        metrics = geometry_metrics(mask)
        assert metrics["eye_cells"]["left"] >= 4
        assert metrics["eye_cells"]["right"] >= 4
        assert metrics["nose_cells"] >= 2
        assert metrics["ear_gap_rows"] >= 2, metrics["ear_gap_rows"]
        assert len(metrics["holes"]) == 3          # two eyes + nose


# ------------------------------------------- v1.5 notch and boundary cells --

def _mask_without_cells(mask: Mask, cells) -> Mask:
    """Copy of ``mask`` with ``cells`` removed from both grid and features."""
    drop = set(cells)
    allowed = [list(row) for row in mask.allowed]
    for row, col in drop:
        allowed[row][col] = False
    features = {name: set(value) - drop for name, value in mask.features.items()}
    return Mask(
        kind=mask.kind,
        width=mask.width,
        height=mask.height,
        allowed=tuple(tuple(row) for row in allowed),
        spans=shapes._spans_from_rows(allowed),
        font_metrics=mask.font_metrics,
        features={name: frozenset(value) for name, value in features.items()},
    )


def test_notch_window_is_a_public_fixed_central_region():
    assert NOTCH_CENTER_FRACTION == 0.5
    assert NOTCH_MIN_WINDOW_CELLS == 3
    assert 0.0 < NOTCH_WINDOW_FRACTION < 0.1
    for cols in (64, 128, 192, 256):
        start, end = shapes._notch_window(cols, NOTCH_CENTER_FRACTION,
                                          NOTCH_WINDOW_FRACTION)
        assert 0 <= start < end <= cols
        assert end - start >= NOTCH_MIN_WINDOW_CELLS
        assert abs((start + end) / 2.0 - cols / 2.0) <= 1.0


def test_ear_notch_survives_a_trimmed_ear_tip():
    """v1.5 reproduction: h32 with three cells removed from the left ear tip.

    The peaks then sit at rows 1 (left) and 0 (right) while the central upper
    boundary is row 5.  The v1.4 rule (global peak row + single mid column)
    returned 0 because the left ear owned no cell on the global peak row; the
    plan-defined depth is ``5 - max(1, 0) = 4``.
    """
    mask = make("cat", 32)
    tip = sorted(cell for cell in mask.features["ear_left"] if cell[0] == 0)
    assert len(tip) == 3
    trimmed = _mask_without_cells(mask, tip)
    assert min(row for row, _ in trimmed.features["ear_left"]) == 1
    assert min(row for row, _ in trimmed.features["ear_right"]) == 0
    assert geometry_metrics(trimmed)["ear_gap_rows"] == 4
    assert ear_notch_rows(trimmed) == 4


def test_ear_notch_uses_the_lower_peak_and_a_fixed_window():
    """A trimmed tip lowers the reference peak by exactly one row."""
    mask = make("cat", 32)
    assert ear_notch_rows(mask) == 5
    tip = sorted(cell for cell in mask.features["ear_left"] if cell[0] == 0)
    trimmed = _mask_without_cells(mask, tip)
    # One row of the *lower* peak is what changed: 5 - 1, not 5 - 0.
    assert ear_notch_rows(trimmed) == ear_notch_rows(mask) - 1


def test_ear_notch_rows_is_zero_without_ears():
    assert ear_notch_rows(make("circle", 32)) == 0
    assert ear_notch_rows(make("code", 32)) == 0


@pytest.mark.parametrize(
    "rows, expected",
    ((32, (31, 31, 14)), (64, (63, 63, 30)), (96, (95, 95, 46)), (128, (125, 125, 62))),
)
def test_hole_boundary_cells_cross_the_analytic_outline(rows, expected):
    """Exact outline-crossed cells for the three cat holes (plan v1.5)."""
    mask = make("cat", rows)
    left, right, nose = expected
    assert hole_boundary_cells(mask, "eye_left") == left
    assert hole_boundary_cells(mask, "eye_right") == right
    assert hole_boundary_cells(mask, "nose") == nose
    assert geometry_metrics(mask)["boundary_cells"] == {
        "eye_left": left, "eye_right": right, "nose": nose,
    }


def test_boundary_cells_are_geometry_only_and_scale_with_the_perimeter():
    """The count comes from the ellipse and the grid, not from ``allowed``."""
    small = hole_boundary_cells(make("cat", 32), "eye_left")
    large = hole_boundary_cells(make("cat", 64), "eye_left")
    assert 1.5 <= large / small <= 2.5           # perimeter grows ~2x per doubling
    with pytest.raises(PipelineError) as info:
        hole_boundary_cells(make("circle", 32), "nose")
    assert info.value.diagnostic.code == ErrorCode.INVALID_SHAPE
    with pytest.raises(PipelineError) as info:
        hole_boundary_cells(make("cat", 32), "tail")
    assert info.value.diagnostic.code == ErrorCode.INVALID_SHAPE


def test_circle_bbox_ratio():
    for rows in (32, 64):
        metrics = geometry_metrics(make("circle", rows))
        assert abs(metrics["bbox"]["ratio"] - 1.0) <= 0.05


def test_determinism():
    for kind in KINDS:
        assert make(kind, 32) == make(kind, 32)
        assert geometry_metrics(make(kind, 32)) == geometry_metrics(make(kind, 32))


def test_scaling_preserves_geometry():
    small = geometry_metrics(make("cat", 32))
    large = geometry_metrics(make("cat", 64))
    for side in ("left", "right"):
        ratio = large["eye_cells"][side] / small["eye_cells"][side]
        assert 3.0 <= ratio <= 5.0, ratio          # area grows ~4x
    nose_ratio = large["nose_cells"] / small["nose_cells"]
    assert 2.7 <= nose_ratio <= 5.3, nose_ratio
    assert large["ear_gap_rows"] >= small["ear_gap_rows"]


# ------------------------------------------------------------------ contracts --

def test_metrics_default_construction_matches_explicit_default():
    """``FontMetrics()`` and ``FontMetrics(0.5)`` are the same metrics."""
    default = FontMetrics()
    explicit = FontMetrics(0.5)
    assert default == explicit
    assert default.cell_aspect == explicit.cell_aspect == 0.5
    assert FontMetrics(cell_aspect=0.5) == default
    assert default.font_id is None
    assert default.cell_width_px is None and default.cell_height_px is None


def test_cell_aspect_is_derived_from_the_cell_size():
    metrics = FontMetrics(font_id="mono", cell_width_px=8, cell_height_px=16)
    assert metrics.cell_aspect == 0.5          # 8 / 16, not a stored constant
    assert metrics.font_id == "mono"
    assert metrics.cell_width_px == 8 and metrics.cell_height_px == 16
    # A different pixel size with the same ratio is still the project ratio.
    assert FontMetrics(cell_width_px=12, cell_height_px=24).cell_aspect == 0.5


def test_cell_aspect_is_a_derived_property():
    assert isinstance(FontMetrics.cell_aspect, property)
    with pytest.raises(AttributeError):
        FontMetrics().cell_aspect = 1.0        # frozen: derived, not assignable


def test_ratio_within_the_tolerance_is_accepted():
    metrics = FontMetrics(0.5 + CELL_ASPECT_TOLERANCE / 2)
    assert metrics.cell_aspect == 0.5


@pytest.mark.parametrize("bad", (0.7, 1.0, 0.25, 0.5 + 2 * CELL_ASPECT_TOLERANCE))
def test_explicit_aspect_other_than_the_project_value_is_rejected(bad):
    with pytest.raises(PipelineError) as info:
        FontMetrics(bad)
    diagnostic = info.value.diagnostic
    assert diagnostic.code == ErrorCode.INVALID_SHAPE
    assert diagnostic.stage == "shape"
    assert diagnostic.location == "FontMetrics.cell_aspect"


def test_pixel_size_with_a_different_ratio_is_rejected():
    with pytest.raises(PipelineError) as info:
        FontMetrics(cell_width_px=10, cell_height_px=10)   # ratio 1.0
    assert info.value.diagnostic.code == ErrorCode.INVALID_SHAPE
    with pytest.raises(PipelineError):
        FontMetrics(cell_width_px=8)                       # height is missing


@pytest.mark.parametrize("bad", (0, -1, True, float("nan")))
def test_malformed_aspect_is_an_invalid_size(bad):
    with pytest.raises(PipelineError) as info:
        FontMetrics(bad)
    assert info.value.diagnostic.code == ErrorCode.INVALID_SIZE


def test_shape_spec_has_no_font_id():
    assert "font_id" not in {name for name in ShapeSpec.__dataclass_fields__}
    with pytest.raises(TypeError):
        ShapeSpec("cat", font_id="mono")


def test_mask_scale_is_derived_from_the_height():
    """``width``/``height`` are the only size authority; ``scale`` follows."""
    assert "scale" not in {name for name in Mask.__dataclass_fields__}
    mask = make("cat", 32)
    assert mask.scale == mask.height / 2
    assert make("cat", 64).scale == 32.0


def test_error_names_are_synonyms():
    assert ShapeError is PipelineError
    assert StageError is PipelineError


# -------------------------------------------------------------------- errors --

def test_inner_radius_is_rejected():
    with pytest.raises(PipelineError) as info:
        build_mask(ShapeSpec("cat", inner_radius=0.5), SizeRequest(32), FontMetrics())
    diagnostic = info.value.diagnostic
    assert diagnostic.code == ErrorCode.INVALID_SHAPE
    assert diagnostic.stage == "shape"
    assert diagnostic.location == "ShapeSpec.inner_radius"
    assert "ring" in diagnostic.message


def test_code_text_must_be_code():
    make("code")                                    # defaults to CODE
    with pytest.raises(PipelineError) as info:
        build_mask(ShapeSpec("code", text="HELLO"), SizeRequest(32), FontMetrics())
    assert info.value.diagnostic.code == ErrorCode.INVALID_SHAPE


def test_invalid_height_rows():
    for bad in (0, -5):
        with pytest.raises(PipelineError) as info:
            build_mask(ShapeSpec("circle"), SizeRequest(bad), FontMetrics())
        diagnostic = info.value.diagnostic
        assert diagnostic.code == ErrorCode.INVALID_SIZE
        assert diagnostic.stage == "shape"
        assert diagnostic.location == "SizeRequest.height_rows"


def test_unknown_kind_is_rejected():
    with pytest.raises(PipelineError) as info:
        build_mask(ShapeSpec("triangle"), SizeRequest(32), FontMetrics())
    assert info.value.diagnostic.code == ErrorCode.INVALID_SHAPE


def test_build_mask_raises_the_shared_pipeline_error():
    """``height_rows=0`` keeps INVALID_SIZE instead of becoming LAYOUT_LIMIT."""
    with pytest.raises(PipelineError) as info:
        build_mask(ShapeSpec("circle"), SizeRequest(height_rows=0), FontMetrics())
    error = info.value
    assert isinstance(error, ShapeError)            # compatibility alias
    assert isinstance(error, StageError)            # canonical alias
    assert error.diagnostic.code == ErrorCode.INVALID_SIZE
    assert error.diagnostic.stage == "shape"


def test_empty_mask_is_rejected(monkeypatch):
    def empty_rows(cols, rows, aspect, ctx):
        return [[False] * cols for _ in range(rows)]

    monkeypatch.setattr(shapes, "_circle_rows", empty_rows)
    with pytest.raises(PipelineError) as info:
        build_mask(ShapeSpec("circle"), SizeRequest(8), FontMetrics())
    diagnostic = info.value.diagnostic
    assert diagnostic.code == ErrorCode.INVALID_SHAPE
    assert diagnostic.stage == "shape"
    assert diagnostic.location == "Mask.allowed"
    assert "fillable" in diagnostic.message


# -------------------------------------------------------------------- ctx --

def test_ctx_duck_typing():
    class Ctx:
        def __init__(self):
            self.calls = 0

        def raise_if_cancelled(self):
            self.calls += 1
            if self.calls > 3:
                raise RuntimeError("cancelled")

    ctx = Ctx()
    with pytest.raises(RuntimeError):
        build_mask(ShapeSpec("circle"), SizeRequest(32), FontMetrics(), ctx=ctx)
    assert ctx.calls == 4

    class PlainCtx:
        def __init__(self):
            self.calls = 0

        def check(self):
            self.calls += 1

    plain = PlainCtx()
    make_mask = build_mask(ShapeSpec("cat"), SizeRequest(8), FontMetrics(), ctx=plain)
    assert make_mask.height == 8
    assert plain.calls == 8


# --------------------------------------------------------------- fixtures --

@pytest.mark.parametrize("kind", KINDS)
def test_fixture_regression(kind):
    path = FIXTURES / f"{kind}_32.json"
    assert path.is_file(), path
    data = json.loads(path.read_text(encoding="utf-8"))
    mask = make(kind, data["height"])
    assert mask.width == data["width"]
    assert mask.height == data["height"]
    assert ["".join("#" if v else "." for v in row) for row in mask.allowed] == data["rows"]
    assert [[list(s) for s in spans] for spans in mask.spans] == data["spans"]
