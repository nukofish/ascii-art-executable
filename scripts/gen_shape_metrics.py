#!/usr/bin/env python3
"""Generate the scaled geometry reference data for the verifier (Part E).

The fixtures under ``tests/fixtures/shapes/metrics_h<rows>.json`` are derived
from the live mask implementation in :mod:`codeart.shapes`.  Nothing in the
JSON is hand-written: every number comes from ``build_mask`` /
``geometry_metrics`` (and, for the cat's holes, ``hole_boundary_cells``) for
the three supported shapes at 32, 64, 96 and 128 rows.

Each named hole also carries ``boundary_cells``: the exact number of grid
cells the analytic outline crosses (plan v1.5), i.e. the area quantisation
error of a centre-sampled hole outlined in cells rather than a
``max(0.02*A, 4*sqrt(A), 2)`` estimate.

``h32``/``h64``/``h128`` are the heights of Part E's scaled cat acceptance set
(``32 * scale`` for ``scale in (1, 2, 4)``); ``h96`` is kept alongside them for
continuity, so nothing that referenced the older three-height set breaks.

The output is deterministic: dict insertion order is fixed, floats are
rounded to a documented number of decimals, and the file always ends with one
newline.  Running the script twice therefore produces byte-identical files.

Usage::

    python scripts/gen_shape_metrics.py
    python scripts/gen_shape_metrics.py --out-dir /tmp/metrics
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from codeart.shapes import (  # noqa: E402
    CELL_ASPECT_DEFAULT,
    FontMetrics,
    ShapeSpec,
    SizeRequest,
    build_mask,
    geometry_metrics,
    hole_boundary_cells,
)

#: 32/64/128 are Part E's scaled cat acceptance heights (32 * scale for
#: scale in (1, 2, 4)); 96 is retained for continuity with the older set.
HEIGHTS = (32, 64, 96, 128)
KINDS = ("circle", "cat", "code")
#: Only the named hole features are part of the public reference schema.
HOLE_FEATURES = ("eye_left", "eye_right", "nose")
SCHEMA_VERSION = 1

#: Tolerance contract consumed by Part E.  Area error is not constant: it scales
#: with the number of boundary cells, i.e. with the hole's perimeter, which grows
#: like sqrt(A).  A single fixed floor is therefore simultaneously too loose for
#: the 10-cell nose at 32 rows and too tight for the 371-cell eye at 96 rows
#: (whose centre-sampling drift is already 16 cells).  The permitted area delta is
#:
#:     max(area_rel * expected, area_perimeter_factor * sqrt(expected), area_min_cells)
#:
#: with ``expected = A_ref * (h / 32) ** 2`` measured against the 32-row reference.
TOLERANCE = {
    "bbox_ratio_abs": 0.05,
    "area_rel": 0.02,
    "area_perimeter_factor": 4.0,
    "area_min_cells": 2,
    "centroid_abs_cells": 1.0,
}
SCALING_NOTE = "面积按 (h/32)^2 缩放；位置按 h/32 缩放；bbox_ratio 与 h 无关"


def _feature_entry(cells, boundary_cells: int) -> dict:
    """Summarise one feature cell set.

    ``bbox`` is inclusive ``[min_row, min_col, max_row, max_col]``.
    ``centroid`` uses cell-centre coordinates (index + 0.5), so that the
    centroid scales exactly with ``height_rows`` instead of carrying the
    half-cell bias of raw indices.
    ``boundary_cells`` is the exact count of grid cells whose edges the hole's
    analytic outline crosses (v1.5); it is the per-hole quantisation bound E
    used to approximate with ``max(0.02*A, 4*sqrt(A), 2)``.
    """
    count = len(cells)
    rows = [row for row, _ in cells]
    cols = [col for _, col in cells]
    return {
        "cells": count,
        "boundary_cells": boundary_cells,
        "bbox": [min(rows), min(cols), max(rows), max(cols)],
        "centroid": [
            round(sum(row + 0.5 for row in rows) / count, 3),
            round(sum(col + 0.5 for col in cols) / count, 3),
        ],
    }


def _shape_entry(kind: str, rows: int) -> dict:
    spec = ShapeSpec(kind, text="CODE" if kind == "code" else None)
    mask = build_mask(spec, SizeRequest(rows), FontMetrics(CELL_ASPECT_DEFAULT))
    metrics = geometry_metrics(mask)

    features = {}
    for name in HOLE_FEATURES:
        cells = mask.features.get(name)
        if cells:
            features[name] = _feature_entry(
                cells,
                hole_boundary_cells(mask, name) if kind == "cat" else 0,
            )

    return {
        "cols": metrics["cols"],
        "rows": metrics["rows"],
        "bbox_ratio": round(metrics["bbox"]["ratio"], 6),
        "allowed_cells": metrics["allowed_cells"],
        "spans_total": metrics["spans_total"],
        "rows_with_multiple_spans": metrics["rows_with_multiple_spans"],
        "features": features,
        # Named eye/nose holes only.  ``geometry_metrics()["holes"]`` can also
        # contain incidental one-cell blank components at some resolutions.
        "hole_count": len(features),
        "ear_gap_rows": metrics["ear_gap_rows"] if kind == "cat" else None,
    }


def build_document(rows: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "cell_aspect": CELL_ASPECT_DEFAULT,
        "height_rows": rows,
        "generated_by": "scripts/gen_shape_metrics.py",
        "tolerance": dict(TOLERANCE),
        "shapes": {kind: _shape_entry(kind, rows) for kind in KINDS},
        "scaling_expectation": {
            "note": SCALING_NOTE,
            "area_scale_ref_height": 32,
        },
    }


def dumps(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "shapes",
        help="directory for metrics_h<rows>.json (default: tests/fixtures/shapes)",
    )
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    if not out_dir.is_absolute():
        out_dir = (Path.cwd() / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    for rows in HEIGHTS:
        path = out_dir / f"metrics_h{rows}.json"
        path.write_text(dumps(build_document(rows)), encoding="utf-8", newline="\n")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
