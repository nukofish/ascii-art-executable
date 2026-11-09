"""Isolated libclang work. The parent owns deadlines and process cleanup."""

import json
from pathlib import Path
import sys


class SourceRejected(Exception):
    def __init__(self, code, message, location=None):
        self.diagnostic = {"code": code, "message": message}
        if location is not None:
            self.diagnostic.update(line=location.line, column=location.column)


def reject(message, location=None, code="UNSUPPORTED_SOURCE"):
    raise SourceRejected(code, message, location)


def process(request):
    import clang.cindex as clang

    text = request["text"]
    # A virtual final LF satisfies strict C11 parsing without changing source positions.
    parsing_text = text if text.endswith("\n") else text + "\n"
    filename = "input.c"
    index = clang.Index.create()
    tu = index.parse(
        filename, args=request["flags"],
        unsaved_files=[(filename, parsing_text)],
        options=clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )
    tokens = []
    for token in tu.get_tokens(extent=tu.cursor.extent):
        spelling = parsing_text[token.extent.start.offset:token.extent.end.offset]
        tokens.append(dict(kind=token.kind.name, spelling=spelling,
                           line=token.location.line, column=token.location.column,
                           is_comment=token.kind == clang.TokenKind.COMMENT))
    if request["mode"] == "lex":
        return {"tokens": tokens}

    for token in tokens:
        if token["is_comment"]:
            continue
        location = type("Position", (), dict(line=token["line"], column=token["column"]))()
        if token["spelling"] in ("#", "%:"):
            reject("Preprocessing directives are unsupported", location)
        if token["spelling"] in ("__func__", "__FUNCTION__", "__PRETTY_FUNCTION__"):
            reject("Function-name builtins are unsupported", location)
        if "\t" in token["spelling"]:
            reject("Real tab characters inside tokens are unsupported", location)

    children = [child for child in tu.cursor.get_children()
                if child.location.file and child.location.file.name == filename]
    for child in children:
        if child.kind == clang.CursorKind.MACRO_INSTANTIATION:
            reject("Predefined macro use is unsupported: " + child.spelling, child.location)

    definitions = []
    for child in children:
        if child.kind == clang.CursorKind.FUNCTION_DECL and child.is_definition():
            definitions.append(child)
        else:
            reject("Only one self-contained function definition is supported", child.location)
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
                reject("External function and object declarations are unsupported", node.location)
        if node.kind == clang.CursorKind.DECL_REF_EXPR:
            referenced = node.referenced
            if referenced is None or referenced.hash not in local_declarations:
                reject("Reference to an external declaration: " + node.spelling, node.location)

    for diagnostic in tu.diagnostics:
        if diagnostic.severity >= clang.Diagnostic.Error:
            code = "INVALID_SOURCE"
            if "undeclared" in diagnostic.spelling or "implicit function" in diagnostic.spelling:
                code = "UNSUPPORTED_SOURCE"
            reject(diagnostic.spelling, diagnostic.location, code)
    return {"tokens": tokens, "function_name": function.spelling,
            "signature": function.result_type.spelling + " " + function.displayname}


if __name__ == "__main__":
    try:
        reply = process(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
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
    print(json.dumps(reply))
