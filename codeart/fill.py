"""Part D: source rendering and optional comment filling.

The layout engine (C) decides where every token goes.  This module only
writes the tokens at their planned cells and fills the remaining fillable
cells with the two comment forms the verifier (E) accepts:

* closed block comments ``/*=...=*/`` inside a span;
* a restricted ``//=...=`` line comment at the tail of the last span.

Where a complete program has spare room, layout can reserve short gaps along
the token stream. Rendering preserves every token's placement and spelling and
respects holes and protected blanks.
"""

from __future__ import annotations

from .contracts import (
    Diagnostic,
    ErrorCode,
    FillOptions,
    LayoutPlan,
    PROGRAM_FILL_PATTERN,
    RenderedCode,
    SourceModel,
    StageError,
    character_cells,
    grid_text,
)

_BLOCK_MIN_CELLS = 4  # "/*" + body + "*/" is at least four cells
_LINE_MIN_CELLS = 2  # "//" is the shortest legal line comment


def _render_error(message: str) -> StageError:
    """A plan the renderer cannot honour is an integration bug, not user input."""
    return StageError(Diagnostic(ErrorCode.INTERNAL_ERROR, "render", message))


def _write_token(token, placement, mask, canvas, occupied) -> None:
    if placement.token_index != token.index:
        raise _render_error(
            f"placement index {placement.token_index} does not match token {token.index}"
        )
    if token.width != len(grid_text(token.spelling)) or token.width <= 0:
        raise _render_error(f"token {token.index} has a bad width")
    row, col = placement.row, placement.col
    end = col + token.width
    if not (0 <= row < mask.height and 0 <= col < end <= mask.width):
        raise _render_error(f"token {token.index} is placed outside the canvas")
    if not all(mask.allowed[row][col:end]):
        raise _render_error(f"token {token.index} covers a non-fillable cell")
    if any(occupied[row][col:end]):
        raise _render_error(f"token {token.index} overlaps another token")
    occupied[row][col:end] = b"\x01" * token.width
    for char in token.spelling:
        canvas[row][col] = char
        cells = character_cells(char)
        if cells == 2:
            canvas[row][col + 1] = ""
        col += cells


def _fill_run(canvas, occupied, row, start, end, at_tail, allow_line, pattern):
    """Fill one contiguous free run of a span and return (block, line) cell counts."""
    left_pad = 1 if start > 0 and occupied[row][start - 1] else 0
    right_pad = 1 if end < len(occupied[row]) and occupied[row][end] else 0
    available = (end - start) - left_pad - right_pad
    line_comment = at_tail and allow_line
    delimiter_cells = _LINE_MIN_CELLS if line_comment else _BLOCK_MIN_CELLS
    if available < delimiter_cells:
        return 0, 0

    left = start + left_pad
    phase = (row * 3 + left) % len(pattern)
    length = end - left if line_comment else available
    body_length = length - delimiter_cells
    body = (pattern * (length // len(pattern) + 2))[phase:phase + body_length]
    if line_comment:
        canvas[row][left:end] = "//" + body
        return 0, length
    canvas[row][left:left + length] = "/*" + body + "*/"
    return length, 0


def render_source(
    model: SourceModel,
    plan: LayoutPlan,
    fill_options: FillOptions,
    *,
    ctx,
) -> RenderedCode:
    mask = plan.mask
    width, height = mask.width, mask.height
    canvas = [[" "] * width for _ in range(height)]
    occupied = [bytearray(width) for _ in range(height)]

    if len(plan.placements) != len(model.tokens):
        raise _render_error("placement count does not match token count")
    for token, placement in zip(model.tokens, plan.placements):
        _write_token(token, placement, mask, canvas, occupied)

    protected = frozenset(plan.protected_blanks)
    for row, col in protected:
        if not (0 <= row < height and 0 <= col < width):
            raise _render_error(f"protected blank {(row, col)} is outside the canvas")
        if occupied[row][col]:
            raise _render_error(f"protected blank {(row, col)} overlaps a token")
        if not mask.allowed[row][col]:
            raise _render_error(f"protected blank {(row, col)} is not fillable")

    block_cells = 0
    line_cells = 0
    pattern = PROGRAM_FILL_PATTERN if getattr(model, "program_mode", False) else "="
    for row in range(height):
        ctx.check()
        spans = mask.spans[row]
        last_span = len(spans) - 1
        for index, (start, end) in enumerate(spans):
            col = start
            while col < end:
                while col < end and (occupied[row][col] or (row, col) in protected):
                    col += 1
                run_start = col
                while col < end and not occupied[row][col] and (row, col) not in protected:
                    col += 1
                if run_start == col:
                    continue
                at_tail = index == last_span and col == end
                added_block, added_line = _fill_run(
                    canvas, occupied, row, run_start, col, at_tail,
                    fill_options.allow_line_comments, pattern,
                )
                block_cells += added_block
                line_cells += added_line

    lines = []
    for row, cells in enumerate(canvas):
        ctx.check()
        last = -1
        for col, char in enumerate(cells):
            if char != " " or occupied[row][col]:
                last = col
        lines.append("".join(cells[: last + 1]))
    source_text = "\n".join(lines) + "\n"

    allowed_total = sum(1 for row in mask.allowed for cell in row if cell)
    token_ink = sum(
        1
        for row in range(height)
        for col in range(width)
        if occupied[row][col] and canvas[row][col] != " "
    )
    comment_cells = {"block": block_cells, "line": line_cells}
    denominator = allowed_total or 1
    return RenderedCode(
        source_text=source_text,
        position_map={item.token_index: (item.row, item.col) for item in plan.placements},
        coverage=(token_ink + block_cells + line_cells) / denominator,
        token_coverage=token_ink / denominator,
        comment_coverage=(block_cells + line_cells) / denominator,
        comment_cells=comment_cells,
    )
