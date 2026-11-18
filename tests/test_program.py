"""Whole-program arrangement keeps the complete translation unit usable."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from codeart import source as source_module
from codeart.contracts import PROGRAM_FILL_PATTERN, GenerationRequest, ShapeSpec
from codeart.pipeline import generate


PROGRAM = """#include <stdio.h>
#define OFFSET 2

typedef struct {
    int base;
} Config;

static Config config = {3};

static int add_value(int value) {
    return value + OFFSET + config.base;
}

int main(void) {
    printf("%d\\n", add_value(4));
    return 0;
}
"""
FILLER_BODY = f"[{re.escape(PROGRAM_FILL_PATTERN)}]*"
FILLER = re.compile(rf"/\*{FILLER_BODY}\*/|//{FILLER_BODY}$", re.MULTILINE)


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_complete_program_is_arranged_and_runs_identically(tmp_path):
    original = tmp_path / "original.c"
    original.write_text(PROGRAM)
    generated_path = tmp_path / "generated.c"
    original_binary = tmp_path / "original"
    generated_binary = tmp_path / "generated"

    result = generate(GenerationRequest(
        PROGRAM, ShapeSpec("cat"), program_mode=True,
    ))

    assert result.status.value == "OK", result.diagnostics
    assert result.rendered.program_mode is True
    assert result.rendered.source_text.startswith("#include <stdio.h>\n#define OFFSET 2\n")
    assert "typedef" in result.rendered.artwork_source_text
    artwork_without_filler = FILLER.sub("", result.rendered.artwork_source_text)
    assert re.search(r"\bint\s+main\b", artwork_without_filler)
    interleaved_rows = 0
    for line in result.rendered.artwork_source_text.splitlines():
        has_filler = FILLER.search(line) is not None
        code_line = FILLER.sub("", line).strip()
        if has_filler and code_line:
            interleaved_rows += 1
    assert interleaved_rows >= 5
    assert result.rendered.comment_coverage > 0
    assert {
        name: getattr(result.verification, name + "_status").value
        for name in ("token", "geometry", "compile")
    } == {"token": "PASS", "geometry": "PASS", "compile": "PASS"}
    assert result.verification.behavior_status.value == "NOT_RUN"

    generated_path.write_text(result.rendered.source_text)
    for source_path, binary_path in (
        (original, original_binary), (generated_path, generated_binary),
    ):
        subprocess.run(
            ["clang", "-std=c11", "-pedantic-errors", str(source_path),
             "-o", str(binary_path)],
            check=True, capture_output=True, text=True, timeout=10,
        )
    original_run = subprocess.run(
        [str(original_binary)], check=True, capture_output=True, text=True, timeout=5,
    )
    generated_run = subprocess.run(
        [str(generated_binary)], check=True, capture_output=True, text=True, timeout=5,
    )
    assert generated_run.stdout == original_run.stdout == "9\n"


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_conditional_block_is_kept_whole_at_the_front():
    source = """#include <stdio.h>
#if 1
int helper(void) { return 7; }
#endif
int main(void) { printf("%d\\n", helper()); return 0; }
"""

    result = generate(GenerationRequest(
        source, ShapeSpec("circle"), program_mode=True,
    ))

    assert result.status.value == "OK", result.diagnostics
    assert result.rendered.preamble_text.startswith(
        "#include <stdio.h>\n#if 1\nint helper(void) { return 7; }\n#endif\n"
    )
    assert "helper(void)" not in result.rendered.artwork_source_text
    assert result.verification.compile_status.value == "PASS"


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_continued_macro_stays_intact_in_the_prefix():
    source = "#define VALUE \\\n  9\nint main(void) { return VALUE; }\n"

    result = generate(GenerationRequest(
        source, ShapeSpec("circle"), program_mode=True,
    ))

    assert result.status.value == "OK", result.diagnostics
    assert result.rendered.preamble_text == "#define VALUE \\\n  9\n\n\n"
    assert result.verification.token_status.value == "PASS"
    assert result.verification.compile_status.value == "PASS"


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_macro_reordering_that_changes_expansion_fails_token_check():
    source = """#define VALUE 1
int first(void) { return VALUE; }
#undef VALUE
#define VALUE 2
int main(void) { return first() + VALUE; }
"""

    result = generate(GenerationRequest(
        source, ShapeSpec("circle"), program_mode=True,
    ))

    assert result.status.value == "FAILED"
    assert result.verification.token_status.value == "FAIL"
    assert result.verification.geometry_status.value == "NOT_RUN"
    assert any("preprocessor output" in item.message
               for item in result.verification.diagnostics)


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_complete_program_accepts_utf8_and_empty_parameter_lists(tmp_path):
    prefix = '#include <stdio.h>\n#define 问候 "你好"\n'
    source = prefix + '''/* 中文注释 */
static int 数量() { return 2; }
int main() { printf(问候 "，世界！%d\\n", 数量()); return 0; }
'''
    result = generate(GenerationRequest(source, ShapeSpec("cat"), program_mode=True))

    assert result.status.value == "OK", result.diagnostics
    assert result.rendered.preamble_text == prefix + "\n\n"
    assert '"，世界！%d\\n"' in result.rendered.artwork_source_text
    assert "数量" in result.rendered.artwork_source_text
    assert re.search(r"\bmain\s*\(\s*\)", FILLER.sub("", result.rendered.artwork_source_text))
    for name in ("token", "geometry", "compile"):
        assert getattr(result.verification, name + "_status").value == "PASS"

    outputs = []
    for name, text in (("original", source), ("generated", result.rendered.source_text)):
        source_path = tmp_path / f"{name}.c"
        binary_path = tmp_path / name
        source_path.write_text(text, encoding="utf-8")
        subprocess.run(
            ["clang", "-std=c11", "-pedantic-errors", "-Wno-strict-prototypes",
             str(source_path), "-o", str(binary_path)],
            check=True, capture_output=True, timeout=10,
        )
        outputs.append(subprocess.check_output([str(binary_path)], timeout=5).decode("utf-8"))
    assert outputs == ["你好，世界！2\n"] * 2


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_complete_program_still_rejects_c_syntax_errors():
    result = generate(GenerationRequest(
        "int main() { int 数量 = ; return 0; }",
        ShapeSpec("circle"), program_mode=True,
    ))

    assert result.status.value == "FAILED"
    assert result.diagnostics[0].code.value == "INVALID_SOURCE"
    assert result.diagnostics[0].column == 23


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_complete_program_uses_compiler_resource_headers(tmp_path, monkeypatch):
    headers = tmp_path / "include"
    headers.mkdir()
    (headers / "codeart_builtin.h").write_text("#define VALUE 42\n")
    compiler_command = source_module.run_command

    def run_command(args, **kwargs):
        if args[-1] == "-print-resource-dir":
            return subprocess.CompletedProcess(args, 0, str(tmp_path) + "\n", "")
        return compiler_command(args, **kwargs)

    monkeypatch.setattr(source_module, "run_command", run_command)
    result = generate(GenerationRequest(
        "#include <codeart_builtin.h>\nint main(void) { return VALUE != 42; }\n",
        ShapeSpec("circle"), program_mode=True,
    ))

    assert result.status.value == "OK", result.diagnostics
    assert result.verification.token_status.value == "PASS"
    assert result.verification.compile_status.value == "PASS"
