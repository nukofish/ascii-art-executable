"""Tests for the scaled shape metrics consumed by the verifier (Part E)."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from codeart import (  # noqa: E402
    FontMetrics,
    ShapeSpec,
    SizeRequest,
    build_mask,
    geometry_metrics,
    hole_boundary_cells,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "shapes"
HEIGHTS = (32, 64, 96, 128)
KINDS = ("circle", "cat", "code")
HOLE_FEATURES = ("eye_left", "eye_right", "nose")
TOLERANCE_KEYS = {
    "bbox_ratio_abs",
    "area_rel",
    "area_perimeter_factor",
    "area_min_cells",
    "centroid_abs_cells",
}


def load(rows: int) -> dict:
    path = FIXTURES / f"metrics_h{rows}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make(kind: str, rows: int):
    return build_mask(
        ShapeSpec(kind, text="CODE" if kind == "code" else None),
        SizeRequest(rows),
        FontMetrics(),
    )


def stats(cells) -> dict:
    """Same conventions as the generator: inclusive bbox, cell-centre centroid."""
    count = len(cells)
    rows = [row for row, _ in cells]
    cols = [col for _, col in cells]
    return {
        "cells": count,
        "bbox": [min(rows), min(cols), max(rows), max(cols)],
        "centroid": [
            sum(row + 0.5 for row in rows) / count,
            sum(col + 0.5 for col in cols) / count,
        ],
    }


def area_tolerance(tol: dict, expected: float) -> float:
    """Permitted absolute area delta at ``expected`` cells.

    Rasterisation error scales with the number of boundary cells, i.e. with the
    hole perimeter (~sqrt(area)), not with a constant.  The relative term still
    dominates for large features and the floor keeps degenerate tiny holes sane.
    """
    return max(
        tol["area_rel"] * expected,
        tol["area_perimeter_factor"] * math.sqrt(expected),
        tol["area_min_cells"],
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ schema --

@pytest.mark.parametrize("rows", HEIGHTS)
def test_document_schema(rows):
    document = load(rows)
    assert document["schema_version"] == 1
    assert document["cell_aspect"] == 0.5
    assert document["height_rows"] == rows
    assert document["generated_by"] == "scripts/gen_shape_metrics.py"
    assert set(document["tolerance"]) == TOLERANCE_KEYS
    assert set(document["shapes"]) == set(KINDS)
    assert document["scaling_expectation"]["area_scale_ref_height"] == 32
    assert document["scaling_expectation"]["note"]
    # v1.5: every named hole carries its exact outline-crossed cell count.
    cat = document["shapes"]["cat"]["features"]
    assert set(cat) == set(HOLE_FEATURES)
    for name, feature in cat.items():
        assert isinstance(feature["boundary_cells"], int), (rows, name)
        assert not isinstance(feature["boundary_cells"], bool)
        assert feature["boundary_cells"] > 0
    for kind in ("circle", "code"):
        assert document["shapes"][kind]["features"] == {}


# -------------------------------------------------- current implementation --

@pytest.mark.parametrize("rows", HEIGHTS)
@pytest.mark.parametrize("kind", KINDS)
def test_fixture_matches_current_implementation(kind, rows):
    document = load(rows)
    expected = document["shapes"][kind]
    tol = document["tolerance"]

    mask = make(kind, rows)
    actual = geometry_metrics(mask)

    assert expected["cols"] == mask.width == actual["cols"]
    assert expected["rows"] == mask.height == actual["rows"]
    assert expected["bbox_ratio"] == pytest.approx(
        actual["bbox"]["ratio"], abs=tol["bbox_ratio_abs"])

    expected_area = expected["allowed_cells"]
    assert abs(actual["allowed_cells"] - expected_area) <= area_tolerance(
        tol, expected_area)
    assert expected["spans_total"] == actual["spans_total"]
    assert expected["rows_with_multiple_spans"] == actual["rows_with_multiple_spans"]

    present = {name for name in HOLE_FEATURES if mask.features.get(name)}
    assert set(expected["features"]) == present

    for name in present:
        got = stats(mask.features[name])
        ref = expected["features"][name]
        assert abs(got["cells"] - ref["cells"]) <= area_tolerance(tol, ref["cells"])
        assert ref["boundary_cells"] == hole_boundary_cells(mask, name)
        assert got["bbox"] == ref["bbox"]
        assert got["centroid"] == pytest.approx(
            ref["centroid"], abs=tol["centroid_abs_cells"])

    assert expected["hole_count"] == len(present)
    if kind == "cat":
        assert expected["ear_gap_rows"] == actual["ear_gap_rows"]
    else:
        assert expected["ear_gap_rows"] is None


@pytest.mark.parametrize("kind", KINDS)
def test_boundary_cells_scale_with_the_hole_perimeter(kind):
    """The outline-crossed count grows like the perimeter (~2x per doubling)."""
    if kind != "cat":
        return
    reference = load(32)["shapes"][kind]["features"]
    for rows in HEIGHTS[1:]:
        scaled = load(rows)["shapes"][kind]["features"]
        for name in HOLE_FEATURES:
            small = reference[name]["boundary_cells"]
            large = scaled[name]["boundary_cells"]
            expected = rows / 32
            ratio = large / small
            assert abs(ratio - expected) <= 0.35 * expected, (kind, name, rows, small, large)


# ------------------------------------------------------- scaling invariant --

@pytest.mark.parametrize("kind", KINDS)
def test_feature_keys_are_identical_at_every_height(kind):
    keysets = [set(load(rows)["shapes"][kind]["features"]) for rows in HEIGHTS]
    assert all(keyset == keysets[0] for keyset in keysets), (kind, keysets)
    assert keysets[0] == (set(HOLE_FEATURES) if kind == "cat" else set())


@pytest.mark.parametrize("kind", KINDS)
def test_feature_areas_scale_with_height_squared(kind):
    reference = load(32)["shapes"][kind]
    tol = load(32)["tolerance"]
    for rows in HEIGHTS[1:]:
        scaled = load(rows)["shapes"][kind]
        assert set(scaled["features"]) == set(reference["features"])
        for name, ref_feature in reference["features"].items():
            expected = ref_feature["cells"] * (rows / 32) ** 2
            got = scaled["features"][name]["cells"]
            assert got >= 1
            assert abs(got - expected) <= area_tolerance(tol, expected), (
                kind, name, rows, got, expected)


# -------------------------------------------------- counterexamples -----------
# The tolerance must reject genuinely wrong geometry, not just pass the real
# implementation.  Both cases below are the kind of bug the contract exists for.

def test_counterexample_inflated_reference_eye_fails_scaling():
    """A reference eye 1.5x too large must fail the scaling invariant.

    An implementation that scales from a wrong reference can be internally
    consistent at every height, so this pins the expectation against the real
    32-row measurement: the genuine data passes the limit, the inflated
    reference does not.
    """
    tol = load(32)["tolerance"]
    eye_ref = load(32)["shapes"]["cat"]["features"]["eye_left"]["cells"]
    inflated_ref = eye_ref * 1.5
    for rows in HEIGHTS[1:]:
        expected = inflated_ref * (rows / 32) ** 2
        got = load(rows)["shapes"]["cat"]["features"]["eye_left"]["cells"]
        limit = area_tolerance(tol, expected)
        assert abs(got - expected) > limit, (rows, got, expected, limit)


def test_counterexample_h96_eye_shrunk_by_100_fails_area_tolerance():
    """The h96 eye losing 100 cells (371 -> 271) must exceed the tolerance.

    Note the margin: the real 371 is 16 cells from the quadratic expectation of
    387, so the limit is ~78.7 and the measurement legitimately passes.  A
    40-cell shrink (331) is still inside that band; 100 cells is a ~26% error
    and is exactly the kind of regression the contract must reject.
    """
    tol = load(96)["tolerance"]
    eye_ref = load(32)["shapes"]["cat"]["features"]["eye_left"]["cells"]
    expected = eye_ref * (96 / 32) ** 2
    limit = area_tolerance(tol, expected)
    measured = load(96)["shapes"]["cat"]["features"]["eye_left"]["cells"]
    assert abs(measured - expected) <= limit, (measured, expected, limit)
    assert abs((measured - 100) - expected) > limit, (measured, expected, limit)


@pytest.mark.parametrize("kind", KINDS)
def test_feature_centroids_scale_linearly(kind):
    reference = load(32)["shapes"][kind]
    tol = load(32)["tolerance"]["centroid_abs_cells"]
    for rows in HEIGHTS[1:]:
        scaled = load(rows)["shapes"][kind]
        for name, ref_feature in reference["features"].items():
            expected = [value * rows / 32 for value in ref_feature["centroid"]]
            got = scaled["features"][name]["centroid"]
            for actual, target in zip(got, expected):
                assert abs(actual - target) <= tol, (
                    kind, name, rows, actual, target)


@pytest.mark.parametrize("kind", KINDS)
def test_bbox_ratio_is_height_invariant(kind):
    ratios = [load(rows)["shapes"][kind]["bbox_ratio"] for rows in HEIGHTS]
    tol = load(32)["tolerance"]["bbox_ratio_abs"]
    assert max(ratios) - min(ratios) <= tol


# ------------------------------------------------------------- generator --

def test_generator_is_idempotent_and_fixtures_are_current(tmp_path):
    script = ROOT / "scripts" / "gen_shape_metrics.py"
    outputs = []
    for run in ("first", "second"):
        out_dir = tmp_path / run
        result = subprocess.run(
            [sys.executable, str(script), "--out-dir", str(out_dir)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        assert "wrote" in result.stdout
        outputs.append(out_dir)

    for rows in HEIGHTS:
        name = f"metrics_h{rows}.json"
        first = outputs[0] / name
        second = outputs[1] / name
        committed = FIXTURES / name
        assert first.read_bytes() == second.read_bytes() == committed.read_bytes()
        assert sha256(first) == sha256(second) == sha256(committed)
