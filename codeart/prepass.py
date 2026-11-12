"""Conservatively extract file-scope definitions; A alone decides eligibility.

This is not a C preprocessor. Conditional regions and ambiguous declarations
are deliberately left to A or reported as ineligible, never rewritten.

The prepass is a lexical locator, not a C parser: it masks comments and
literals, finds balanced top-level braces, and asks A to validate each
candidate.  A's returned ``function_name`` is authoritative, so declarators
that the locator cannot name itself (function pointers, parenthesised names)
are still selected correctly.
"""
from dataclasses import dataclass, field
import re
from time import monotonic

from .contracts import ErrorCode, RunContext, StageError
from .source import analyze_source

SCOPE = "Only the extracted function is verified, not the entire input program."


@dataclass
class FunctionCandidate:
    name: str
    start_line: int
    end_line: int
    source_text: str
    a_status: str
    diagnostic: dict | None = None
    start_column: int = 1
    end_column: int = 1
    start_offset: int = 0
    end_offset: int = 0


@dataclass
class PrepassResult:
    candidates: list = field(default_factory=list)
    ignored_lines: list = field(default_factory=list)
    ignored_segments: list = field(default_factory=list)
    selected: str | None = None
    validation_scope: str = SCOPE
    error: str | None = None


def _blank(match):
    """Replace a matched span with spaces while preserving newlines/offsets."""
    return ''.join('\n' if char == '\n' else ' ' for char in match.group(0))


def _mask_comments_and_literals(text):
    """Hide comments and literal bodies, preserving offsets and newlines."""
    pattern = r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    return re.sub(pattern, _blank, text, flags=re.S)


def _mask_directives(masked):
    """Hide directive lines, including backslash continuations, for braces."""
    output = []
    continuation = False
    for line in masked.splitlines(keepends=True):
        directive = continuation or line.lstrip().startswith('#')
        continuation = directive and line.rstrip('\n').endswith('\\')
        output.append(''.join('\n' if c == '\n' else ' ' for c in line) if directive else line)
    return ''.join(output)


def _conditional_lines(masked_code):
    """Return lines inside a conditional region, ignoring comments/literals.

    ``masked_code`` already has comments and literal bodies replaced by
    spaces.  Directive continuations are skipped, so a ``#if`` inside a macro
    body does not open a conditional region.
    """
    lines = set()
    level = 0
    continuation = False
    for number, line in enumerate(masked_code.splitlines(), 1):
        directive = not continuation and line.lstrip().startswith('#')
        if directive:
            body = line.lstrip()[1:].lstrip()
            if re.match(r'(?:if|ifdef|ifndef)\b', body):
                level += 1
            elif re.match(r'endif\b', body):
                level = max(0, level - 1)
            if level:
                lines.add(number)
        elif level:
            lines.add(number)
        if (directive or continuation) and line.endswith('\\'):
            continuation = True
        else:
            continuation = False
    return lines


def _line_col(text, offset):
    """Return the one-based line and column for an offset in ``text``."""
    line = text.count('\n', 0, offset) + 1
    line_start = text.rfind('\n', 0, offset) + 1
    return line, offset - line_start + 1


def _file_end(text):
    parts = text.split('\n')
    return len(parts), len(parts[-1]) + 1


def _normalise(text):
    """Strip a leading BOM and normalise CRLF/lone CR to LF for extraction."""
    if text.startswith('\ufeff'):
        text = text[1:]
    return text.replace('\r\n', '\n').replace('\r', '\n')


def _ignored_lines(text, chosen):
    total = len(text.splitlines())
    if chosen is None:
        return [{'start_line': 1, 'end_line': total, 'reason': 'No function selected'}] if total else []
    result = []
    for start, end in ((1, chosen.start_line - 1), (chosen.end_line + 1, total)):
        if start <= end:
            result.append({'start_line': start, 'end_line': end,
                           'reason': 'Outside the selected function'})
    return result


def _ignored_segments(text, chosen):
    """Return precise ignored ranges, including same-line prefixes/suffixes."""
    if not text:
        return []
    file_end = _file_end(text)
    if chosen is None:
        return [{
            'start_line': 1, 'start_column': 1,
            'end_line': file_end[0], 'end_column': file_end[1],
            'reason': 'No function selected',
        }]
    result = []
    start = (chosen.start_line, chosen.start_column)
    end = (chosen.end_line, chosen.end_column)
    if start != (1, 1) and text[:chosen.start_offset].strip():
        result.append({
            'start_line': 1, 'start_column': 1,
            'end_line': start[0], 'end_column': start[1],
            'reason': 'Outside the selected function',
        })
    if end != file_end and text[chosen.end_offset:].strip():
        result.append({
            'start_line': end[0], 'start_column': end[1],
            'end_line': file_end[0], 'end_column': file_end[1],
            'reason': 'Outside the selected function',
        })
    return result


def _diagnostic(code, line, column, message):
    return {'code': code, 'line': line, 'column': column, 'message': message}


def inspect_file(text, function=None, *, analyzer=analyze_source, timeout_s=30, ctx=None):
    """Return raw candidates with A diagnostics mapped to original file lines.

    ``text`` is normalised to LF (and a leading BOM is stripped) before
    extraction.  Candidate ``source_text`` therefore uses LF, matching the
    project's normalised-source convention.
    """
    result = PrepassResult()
    text = _normalise(text)
    if function is not None and not isinstance(function, str):
        result.error = 'INVALID_FUNCTION_SELECTOR'
        result.ignored_lines = _ignored_lines(text, None)
        result.ignored_segments = _ignored_segments(text, None)
        return result

    ctx = ctx or RunContext(monotonic() + timeout_s)
    ctx.check()
    masked_code = _mask_comments_and_literals(text)
    masked = _mask_directives(masked_code)
    conditional_lines = _conditional_lines(masked_code)

    depth = 0
    boundary = 0
    opening = None
    for index, character in enumerate(masked):
        ctx.check()
        if character == '{':
            if depth == 0:
                header = masked[boundary:index]
                match = re.search(
                    r'\b([A-Za-z_][A-Za-z_0-9]*)\s*\([^;{}]*\)\s*$', header)
                opening = (boundary, match[1]) if match and '=' not in header else None
            depth += 1
        elif character == '}':
            depth = max(0, depth - 1)
            if depth == 0:
                if opening:
                    start, name_hint = opening
                    while start < index and masked[start].isspace():
                        start += 1
                    line_start = text.rfind('\n', 0, start) + 1
                    column_offset = start - line_start
                    if not text[line_start:start].strip():
                        start = line_start
                        column_offset = 0
                    start_line, start_column = _line_col(text, start)
                    end_offset = index + 1
                    end_line, end_column = _line_col(text, end_offset)
                    raw = text[start:end_offset]
                    diagnostic = None
                    name = name_hint

                    conditional = bool(
                        conditional_lines.intersection(range(start_line, end_line + 1)))
                    if conditional:
                        diagnostic = _diagnostic(
                            'UNSUPPORTED_SOURCE', start_line, 1,
                            'Conditional preprocessing region is not extracted')
                    else:
                        try:
                            model = analyzer(raw, ctx=ctx)
                            name = model.function_name or name_hint
                        except StageError as exc:
                            error = exc.diagnostic
                            if error.code in (ErrorCode.CANCELLED, ErrorCode.PIPELINE_TIMEOUT):
                                raise
                            diagnostic = _diagnostic(
                                error.code.value,
                                start_line + error.line - 1 if error.line else None,
                                (error.column + column_offset
                                 if error.column and error.line == 1 else error.column),
                                error.message,
                            )
                    if name == 'main' and diagnostic is None:
                        diagnostic = _diagnostic(
                            'UNSUPPORTED_SOURCE', start_line, 1, 'main is excluded')

                    result.candidates.append(FunctionCandidate(
                        name=name,
                        start_line=start_line,
                        end_line=end_line,
                        source_text=raw,
                        a_status='FAIL' if diagnostic else 'PASS',
                        diagnostic=diagnostic,
                        start_column=start_column,
                        end_column=end_column,
                        start_offset=start,
                        end_offset=end_offset,
                    ))
                boundary = index + 1
                opening = None
        elif character == ';' and depth == 0:
            boundary = index + 1

    eligible = [candidate for candidate in result.candidates
                if candidate.a_status == 'PASS'
                and (function is None or candidate.name == function)]
    names = [candidate.name for candidate in eligible]
    if function is not None:
        if len(eligible) > 1:
            result.error = 'AMBIGUOUS_FUNCTION'
        elif eligible:
            result.selected = eligible[0].name
        else:
            result.error = 'NO_ELIGIBLE_FUNCTION'
    elif len(names) != len(set(names)):
        result.error = 'AMBIGUOUS_FUNCTION'
    elif eligible:
        result.selected = eligible[0].name
    else:
        result.error = 'NO_ELIGIBLE_FUNCTION'

    chosen = next((candidate for candidate in eligible
                   if candidate.name == result.selected), None)
    result.ignored_lines = _ignored_lines(text, chosen)
    result.ignored_segments = _ignored_segments(text, chosen)
    return result


def selected_source(result):
    """Return the selected candidate's raw function text."""
    for candidate in result.candidates:
        if candidate.name == result.selected and candidate.a_status == 'PASS':
            return candidate.source_text
    raise ValueError("No selected candidate")
