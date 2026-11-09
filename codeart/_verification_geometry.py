"""Geometry checks against the rendered characters and B's existing mask."""

from __future__ import annotations

import math
import re

from .procutil import check_context
from .shapes import geometry_metrics


_HOLES = {
    "cat": ("eye_left", "eye_right", "nose"),
    "code": ("code_strokes",),
}
_FILL_COMMENT = re.compile(r"/\*=*\*/|//=*")


class _Issues:
    def __init__(self):
        self.reasons = {}
        self.first_cell = None

    def add(self, reason, cell=None):
        self.reasons.setdefault(reason, None)
        if self.first_cell is None and cell is not None:
            self.first_cell = cell


def _token_cells(model, plan, rendered, rows, actual_tokens, ctx, issues):
    mask = plan.mask
    occupied = [bytearray(mask.width) for _ in range(mask.height)]
    positions = {}
    previous = (-1, -1)
    if len(plan.placements) != len(model.tokens):
        issues.add("placement_count")
    for index, (token, placement) in enumerate(zip(model.tokens, plan.placements)):
        check_context(ctx)
        row, col = placement.row, placement.col
        cell = (row, col)
        end = col + token.width
        if (placement.token_index != token.index or token.index in positions
                or cell <= previous):
            issues.add("placement_order", cell)
        positions[token.index] = cell
        previous = cell
        if (token.width != len(token.spelling) or token.width <= 0
                or not (0 <= row < mask.height and 0 <= col < end <= mask.width)):
            issues.add("placement_bounds", cell)
            continue
        if not all(mask.allowed[row][col:end]):
            issues.add("placement_outside_mask", cell)
        if any(occupied[row][col:end]):
            issues.add("placement_overlap", cell)
        occupied[row][col:end] = b"\x01" * token.width
        if rows[row][col:end] != token.spelling:
            issues.add("placement_text", cell)
        if actual_tokens is not None:
            actual = actual_tokens[index]
            if (actual.line - 1, actual.column - 1) != cell:
                issues.add("lexed_position", cell)
    if rendered.position_map != positions:
        issues.add("position_map")
    for row, col in plan.protected_blanks:
        if not (0 <= row < mask.height and 0 <= col < mask.width):
            issues.add("protected_blank_bounds", (row, col))
        elif occupied[row][col] or rows[row][col:col + 1] not in ("", " "):
            issues.add("protected_blank_filled", (row, col))
    return occupied


def _count_filler(text, occupied, allowed, row, counts, issues):
    """Recognize D's restricted fill grammar outside planned token cells."""
    col = 0
    while col < len(occupied) and col < len(text):
        if occupied[col] or text[col] == " ":
            col += 1
            continue
        comment = _FILL_COMMENT.match(text, col)
        if comment is None:
            issues.add("unexpected_filler", (row, col))
            col += 1
            continue
        end = comment.end()
        is_line = text.startswith("//", col)
        if end > len(occupied) or any(occupied[col:end]) or not all(allowed[col:end]):
            issues.add("comment_placement", (row, col))
        if (col > 0 and occupied[col - 1]) or (end < len(occupied) and occupied[end]):
            issues.add("comment_boundary", (row, col))
        if is_line and (any(allowed[end:]) or any(occupied[end:]) or text[end:].strip()):
            issues.add("line_comment_tail", (row, col))
        counts["line" if is_line else "block"] += sum(
            cell_allowed and not cell_occupied
            for cell_allowed, cell_occupied in zip(allowed[col:end], occupied[col:end])
        )
        col = end


def check_geometry(model, plan, rendered, actual_tokens, ctx):
    mask = plan.mask
    issues = _Issues()
    if (mask.width <= 0 or mask.height <= 0 or len(mask.allowed) != mask.height
            or any(len(row) != mask.width for row in mask.allowed)):
        issues.add("mask_dimensions")
        return {}, issues

    parts = rendered.source_text.split("\n")
    if parts[-1] == "":
        parts.pop()
    else:
        issues.add("missing_final_lf")
    if len(parts) != mask.height:
        issues.add("canvas_height")
    rows = parts[:mask.height] + [""] * max(0, mask.height - len(parts))
    occupied = _token_cells(model, plan, rendered, rows, actual_tokens, ctx, issues)

    feature_names = _HOLES.get(mask.kind, ())
    holes = set()
    for name in feature_names:
        cells = mask.features.get(name, ())
        if not cells:
            issues.add(f"missing_{name}")
        holes.update(cells)
    for name, cells in mask.features.items():
        check_context(ctx)
        for row, col in cells:
            if not (0 <= row < mask.height and 0 <= col < mask.width):
                issues.add("feature_bounds", (row, col))
            elif name in feature_names and mask.allowed[row][col]:
                issues.add("fillable_hole", (row, col))

    ink = 0
    token_ink = 0
    outside_canvas = 0
    outside_mask = 0
    hole_leakage = 0
    comment_cells = {"block": 0, "line": 0}
    for row, text in enumerate(parts):
        check_context(ctx)
        if len(text) > mask.width:
            issues.add("canvas_width", (row, mask.width))
        for col, char in enumerate(text):
            if not " " <= char <= "~":
                issues.add("non_printable_ascii", (row, col))
            if char.isspace():
                continue
            if row >= mask.height or col >= mask.width:
                outside_canvas += 1
                issues.add("ink_outside_canvas", (row, col))
            else:
                if (row, col) in holes:
                    hole_leakage += 1
                    issues.add("hole_leakage", (row, col))
                if mask.allowed[row][col]:
                    ink += 1
                    token_ink += occupied[row][col]
                else:
                    outside_mask += 1
                    issues.add("ink_outside_mask", (row, col))
        if row < mask.height:
            _count_filler(text, occupied[row], mask.allowed[row], row, comment_cells, issues)

    check_context(ctx)
    metrics = geometry_metrics(mask)
    check_context(ctx)
    allowed_cells = metrics["allowed_cells"]
    if allowed_cells == 0:
        issues.add("empty_mask")
    if mask.kind == "circle":
        if not 0.95 <= metrics["bbox"]["ratio"] <= 1.05:
            issues.add("circle_ratio")
        if metrics["holes"]:
            issues.add("circle_hole")
    if mask.kind == "cat" and mask.height >= 32:
        if (min(metrics["eye_cells"].values()) < 4 or metrics["nose_cells"] < 2
                or metrics["ear_gap_rows"] < 2 or len(metrics["holes"]) != 3):
            issues.add("cat_features")

    ear_coverage = {}
    for name in ("ear_left", "ear_right"):
        cells = mask.features.get(name, ())
        if cells and "feature_bounds" not in issues.reasons:
            ear_ink = sum(bool(rows[r][c:c + 1].strip()) for r, c in cells)
            ear_coverage[name] = ear_ink / len(cells)
    denominator = allowed_cells or 1
    metrics.update(
        outside_canvas_cells=outside_canvas,
        outside_mask_cells=outside_mask,
        out_of_bounds_cells=outside_canvas + outside_mask,
        hole_leakage_cells=hole_leakage,
        coverage=ink / denominator,
        token_coverage=token_ink / denominator,
        comment_coverage=sum(comment_cells.values()) / denominator,
        comment_cells=comment_cells,
        ear_coverage=ear_coverage,
    )
    for field in ("coverage", "token_coverage", "comment_coverage"):
        if not math.isclose(getattr(rendered, field), metrics[field], abs_tol=1e-9, rel_tol=0):
            issues.add(f"reported_{field}")
    if rendered.comment_cells != comment_cells:
        issues.add("reported_comment_cells")
    return metrics, issues
