"""Guard the ownership boundary between Part A and Part E.

Part A used to import E's private `_verification_process` module. The process
helpers now live in the public `codeart.procutil` module. These checks fail if a
private cross-owner import comes back, so a refactor on one side cannot break
the other silently.
"""

import ast
from pathlib import Path

from codeart import procutil, source

PACKAGE = Path(__file__).resolve().parents[1] / "codeart"

A_PRIVATE_MODULES = {"_source_lexer", "_source_worker"}
E_PRIVATE_MODULES = {"_verification_process", "_verification_geometry", "verify"}


def imported_modules(path):
    """Return the `codeart.<name>` modules a file imports, ignoring the rest."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                if node.module:
                    names.add(node.module.split(".")[0])
            elif node.module and node.module.startswith("codeart."):
                names.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("codeart."):
                    names.add(alias.name.split(".")[1])
    return names


GRAPH = {path.stem: imported_modules(path) for path in PACKAGE.glob("*.py")}


def test_a_private_lexer_modules_have_one_importer():
    for module, imports in GRAPH.items():
        leaked = A_PRIVATE_MODULES & imports
        if leaked:
            assert module == "source", f"{module} imports A's private modules {leaked}"


def test_a_does_not_import_final_stage_private_modules():
    assert GRAPH["source"] & E_PRIVATE_MODULES == set()


def test_compatibility_shim_is_not_used_inside_the_package():
    for module, imports in GRAPH.items():
        assert "_verification_process" not in imports, module


def test_a_depends_on_shared_modules_only():
    assert GRAPH["source"] <= {"contracts", "procutil", "_source_lexer", "shapes"}
    assert GRAPH["_source_lexer"] <= {"contracts", "procutil"}


def test_procutil_public_surface_is_complete():
    assert set(procutil.__all__) == {
        "BuildFailed", "BuildSession", "CommandTimedOut", "DependencyUnavailable",
        "WorkStopped", "check_context", "run_command", "stop_process",
    }
    for name in procutil.__all__:
        assert hasattr(procutil, name), name


def test_source_public_surface_is_explicit():
    assert source.__all__ == (
        "analyze_program", "analyze_source", "can_join", "lex_source", "prepare_profile",
    )
    for name in source.__all__:
        assert callable(getattr(source, name)), name
