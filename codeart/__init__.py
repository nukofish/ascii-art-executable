"""codeart — code-art layout toolkit.

B's module lives in :mod:`codeart.shapes`: it turns a shape request into a
:class:`~codeart.shapes.Mask` describing which cells the renderer may fill.
"""

from .shapes import (
    CELL_ASPECT_DEFAULT,
    CELL_ASPECT_TOLERANCE,
    HOLE_ELLIPSES,
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

__all__ = [
    "CELL_ASPECT_DEFAULT",
    "CELL_ASPECT_TOLERANCE",
    "HOLE_ELLIPSES",
    "NOTCH_CENTER_FRACTION",
    "NOTCH_MIN_WINDOW_CELLS",
    "NOTCH_WINDOW_FRACTION",
    "FontMetrics",
    "Mask",
    "ShapeError",
    "ShapeSpec",
    "SizeRequest",
    "build_mask",
    "ear_notch_rows",
    "geometry_metrics",
    "hole_boundary_cells",
]

__version__ = "0.2.0"
