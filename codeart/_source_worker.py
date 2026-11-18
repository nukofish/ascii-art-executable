"""Isolated libclang work. The parent owns deadlines and process cleanup.

The worker returns raw tokens for Part E's reuse and performs the input checks
that need a real C11 parse for Part A. It never imports the pipeline, never
starts children of its own and never decides budgets: the parent kills and
reaps this process.
"""

from functools import lru_cache
import json
from pathlib import Path
import sys


class SourceRejected(Exception):
    def __init__(self, code, message, location=None):
        self.diagnostic = {"code": code, "message": message}
        if location is not None:
            self.diagnostic.update(line=location.line, column=location.column)


class Location:
    """One-based source position used for rejection diagnostics."""

    __slots__ = ("line", "column")

    def __init__(self, line, column):
        self.line = line
        self.column = column

    @classmethod
    def from_token(cls, token):
        return cls(token["line"], token["column"])

    @classmethod
    def from_cursor(cls, cursor, utf8_lines=()):
        location = cursor.location
        if location is None or location.line <= 0:
            return None
        return cls(location.line, _character_column(utf8_lines, location))


def _character_column(utf8_lines, location):
    """Convert libclang's UTF-8 byte column to a one-based character column."""
    if 0 < location.line <= len(utf8_lines) and location.column > 0:
        prefix = utf8_lines[location.line - 1][:location.column - 1]
        return len(prefix.decode("utf-8", errors="ignore")) + 1
    return location.column


def reject(message, location=None, code="UNSUPPORTED_SOURCE"):
    raise SourceRejected(code, message, location)


# Names this profile predefines. The table is checked on raw identifier tokens
# so a use is rejected even when libclang's cursor tree does not surface a
# MACRO_INSTANTIATION; the cursor check below still covers every other
# implementation macro such as __INT_MAX__ or __SIZEOF_INT__.
PREDEFINED_MACROS = frozenset({
    "__BASE_FILE__", "__COUNTER__", "__DATE__", "__FILE__", "__FILE_NAME__",
    "__INCLUDE_LEVEL__", "__LINE__", "__TIME__", "__TIMESTAMP__",
    "__STDC__", "__STDC_HOSTED__", "__STDC_VERSION__", "__STDC_UTF_16__",
    "__STDC_UTF_32__", "__STDC_IEC_559__", "__STDC_IEC_559_COMPLEX__",
    "__STDC_ISO_10646__", "__STDC_NO_ATOMICS__", "__STDC_NO_COMPLEX__",
    "__STDC_NO_THREADS__", "__STDC_NO_VLA__",
    "__GNUC__", "__GNUC_MINOR__", "__GNUC_PATCHLEVEL__",
    "__clang__", "__clang_major__", "__clang_minor__", "__clang_patchlevel__",
    "__VERSION__", "__OPTIMIZE__", "__OPTIMIZE_SIZE__", "__NO_INLINE__",
    "__CHAR_BIT__", "__SIZEOF_INT__", "__SIZEOF_LONG__", "__SIZEOF_POINTER__",
    "__ORDER_LITTLE_ENDIAN__", "__ORDER_BIG_ENDIAN__", "__ORDER_PDP_ENDIAN__",
    "__BYTE_ORDER__", "__INT_MAX__", "__INT_MIN__", "__LONG_MAX__",
    "__FINITE_MATH_ONLY__", "__FLT_EVAL_METHOD__", "__ELF__", "__APPLE__",
    "__MACH__", "__unix__", "__unix", "__GNUC_STDC_INLINE__",
    "__has_include", "__has_include_next", "__has_feature", "__has_builtin",
    "__has_attribute", "__has_extension", "__has_cpp_attribute",
})

# C11 defines __func__; these spellings are compiler-specific extensions.
FUNCTION_NAME_EXTENSIONS = frozenset({
    "__FUNCTION__", "__PRETTY_FUNCTION__", "__FUNCSIG__",
})

# Only rejected when libclang lexes them as keywords. Spelled as an ordinary
# identifier (`int typeof = 1;`) a name stays legal C11 and is accepted.
EXTENSION_KEYWORDS = frozenset({
    "asm", "__asm", "__asm__", "__attribute", "__attribute__", "__declspec",
    "__extension__", "__thread", "__typeof", "__typeof__", "_Float16", "__int128",
})


@lru_cache(maxsize=1)
def _index():
    from clang.cindex import Index
    return Index.create()


def _check_tokens(tokens, *, program_mode=False):
    """Reject spellings that the pipeline cannot reproduce in a character grid."""
    for token in tokens:
        if token["is_comment"]:
            continue
        spelling = token["spelling"]
        location = Location.from_token(token)
        if spelling in ("#", "%:") and not program_mode:
            reject("Preprocessing directives are unsupported", location)
        if token["kind"] == "KEYWORD" and spelling in EXTENSION_KEYWORDS:
            reject("Compiler extensions are unsupported: " + spelling, location)
        if spelling in PREDEFINED_MACROS and not program_mode:
            reject("Predefined macro use is unsupported: " + spelling, location)
        if spelling in FUNCTION_NAME_EXTENSIONS:
            reject("Compiler extensions are unsupported: " + spelling, location)
        if "\t" in spelling:
            reject("Real tab characters inside tokens are unsupported", location)
        if "\r" in spelling or "\n" in spelling:
            reject("Line splices inside tokens are unsupported", location)


def _check_declarations(tu, clang, filename):
    """Require one self-contained definition whose references resolve locally."""
    children = [child for child in tu.cursor.get_children()
                if child.location.file and child.location.file.name == filename]
    for child in children:
        if child.kind == clang.CursorKind.MACRO_INSTANTIATION:
            reject("Predefined macro use is unsupported: " + child.spelling,
                   Location.from_cursor(child))

    definitions = []
    for child in children:
        if child.kind == clang.CursorKind.FUNCTION_DECL and child.is_definition():
            definitions.append(child)
        else:
            reject("Only one self-contained function definition is supported",
                   Location.from_cursor(child))
    if len(definitions) != 1:
        reject("Source must contain exactly one function definition", code="INVALID_SOURCE")
    function = definitions[0]

    nodes = list(function.walk_preorder())
    local_declarations = {node.hash for node in nodes if node.kind.is_declaration()}
    for node in nodes:
        if node.kind in (clang.CursorKind.FUNCTION_DECL, clang.CursorKind.VAR_DECL):
            if node.storage_class == clang.StorageClass.EXTERN or (
                node.kind == clang.CursorKind.FUNCTION_DECL and node != function
            ):
                reject("External function and object declarations are unsupported",
                       Location.from_cursor(node))
        if node.kind == clang.CursorKind.DECL_REF_EXPR:
            referenced = node.referenced
            if referenced is None or referenced.hash not in local_declarations:
                reject("Reference to an external declaration: " + node.spelling,
                       Location.from_cursor(node))
    return function


def process(request):
    import clang.cindex as clang

    text = request["text"]
    # A virtual final LF satisfies strict C11 parsing without changing source positions.
    parsing_text = text if text.endswith("\n") else text + "\n"
    utf8 = parsing_text.encode("utf-8")
    utf8_lines = () if parsing_text.isascii() else utf8.split(b"\n")
    filename = "input.c"
    index = _index()
    tu = index.parse(
        filename, args=request["flags"],
        unsaved_files=[(filename, parsing_text)],
        options=clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )
    tokens = []
    for token in tu.get_tokens(extent=tu.cursor.extent):
        if request["mode"] == "program" and (
            token.location.file is None or token.location.file.name != filename
        ):
            continue
        spelling = utf8[token.extent.start.offset:token.extent.end.offset].decode("utf-8")
        tokens.append(dict(kind=token.kind.name, spelling=spelling,
                           line=token.location.line,
                           column=_character_column(utf8_lines, token.location),
                           is_comment=token.kind == clang.TokenKind.COMMENT))
    if request["mode"] == "lex":
        return {"tokens": tokens}

    if request["mode"] == "program":
        _check_tokens(tokens, program_mode=True)
        for diagnostic in tu.diagnostics:
            if diagnostic.severity >= clang.Diagnostic.Error:
                code = "INVALID_SOURCE"
                if "undeclared" in diagnostic.spelling or "implicit function" in diagnostic.spelling:
                    code = "UNSUPPORTED_SOURCE"
                location = diagnostic.location
                lines = utf8_lines if location.file and location.file.name == filename else ()
                reject(diagnostic.spelling, Location.from_cursor(diagnostic, lines), code)
        has_main = any(
            child.kind == clang.CursorKind.FUNCTION_DECL
            and child.spelling == "main"
            and child.is_definition()
            and child.location.file
            and child.location.file.name == filename
            for child in tu.cursor.get_children()
        )
        return {"tokens": tokens, "has_main": has_main}

    _check_tokens(tokens)
    function = _check_declarations(tu, clang, filename)

    for diagnostic in tu.diagnostics:
        if diagnostic.severity >= clang.Diagnostic.Error:
            code = "INVALID_SOURCE"
            if "undeclared" in diagnostic.spelling or "implicit function" in diagnostic.spelling:
                code = "UNSUPPORTED_SOURCE"
            reject(diagnostic.spelling, Location.from_cursor(diagnostic), code)
    return {"tokens": tokens, "function_name": function.spelling,
            "signature": function.result_type.spelling + " " + function.displayname}


def reply_for(request):
    try:
        reply = process(request)
    except SourceRejected as exc:
        reply = {"error": exc.diagnostic}
    except (ImportError, OSError) as exc:
        reply = {"error": {"code": "DEPENDENCY_UNAVAILABLE", "message": str(exc)}}
    except Exception as exc:
        # libclang reports a missing/mismatched native library through LibclangError.
        if type(exc).__name__ == "LibclangError":
            reply = {"error": {"code": "DEPENDENCY_UNAVAILABLE", "message": str(exc)}}
        else:
            raise
    return reply


if __name__ == "__main__":
    if sys.argv[1] == "--serve":
        for line in sys.stdin:
            print(json.dumps(reply_for(json.loads(line))), flush=True)
    else:
        request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        print(json.dumps(reply_for(request)))
