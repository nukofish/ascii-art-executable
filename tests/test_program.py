"""Whole-program arrangement keeps the complete translation unit usable."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from codeart import source as source_module
from codeart.contracts import PROGRAM_FILL_PATTERN, GenerationRequest, LayoutOptions, ShapeSpec
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
@pytest.mark.parametrize("repeats", [120, 180], ids=["244-lines", "364-lines"])
def test_complete_program_fits_five_second_layout_budget(repeats):
    lines = ["int main(void) {", "    unsigned a = 1u, b = 0u;"]
    for index in range(repeats):
        lines.extend([
            f"    b = b + a * {index}u + ({index}u % 7u);",
            f"    if (b > {index * 10}u) {{ a = a - {index}u; }} "
            f"else {{ a = a + {index}u; }}",
        ])
    lines.extend(["    return (a + b) % 100u;", "}"])
    source = "\n".join(lines) + "\n"

    source_module._can_join_cached.cache_clear()
    result = generate(GenerationRequest(
        source, ShapeSpec("cat"), layout_options=LayoutOptions(layout_timeout_s=5),
        program_mode=True,
    ))

    assert result.status.value == "OK", result.diagnostics
    assert result.verification.token_status.value == "PASS"
    assert result.verification.geometry_status.value == "PASS"
    assert result.verification.compile_status.value == "PASS"


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
    source = """static int N = 1;
int first(void) { return N; }
#define N 2
int main(void) { return first() + N; }
"""

    result = generate(GenerationRequest(
        source, ShapeSpec("circle"), program_mode=True,
    ))

    assert result.status.value == "FAILED"
    assert result.verification.token_status.value == "FAIL"
    assert result.verification.geometry_status.value == "NOT_RUN"
    diagnostic = next(item for item in result.verification.diagnostics
                      if item.code.value == "TOKEN_MISMATCH")
    assert "macro expansion" in diagnostic.message
    # The position names the user's own line, not a line of preprocessor output.
    assert (diagnostic.line, diagnostic.column) == (1, None)
    assert result.verification.first_diff.expected.line == 1


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_undef_after_program_code_is_rejected_where_it_appears():
    source = """#define VALUE 1
int first(void) { return VALUE; }
#undef VALUE
int main(void) { return first(); }
"""

    result = generate(GenerationRequest(source, ShapeSpec("circle"), program_mode=True))

    assert result.status.value == "FAILED"
    assert result.diagnostics[0].code.value == "UNSUPPORTED_SOURCE"
    assert result.diagnostics[0].line == 3
    assert "#undef" in result.diagnostics[0].message


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
@pytest.mark.parametrize("source, line", [
    # Inside a function body, e.g. a platform-specific screen clear.
    ("#include <stdio.h>\nstatic void clear(void) {\n#ifdef _WIN32\n"
     "    puts(\"cls\");\n#else\n    puts(\"clear\");\n#endif\n}\n"
     "int main(void) { clear(); return 0; }\n", 3),
    # At file scope after earlier code. Moving it would break -DDEBUG builds.
    ("#include <stdio.h>\nstatic void show(void) { puts(\"x\"); }\n"
     "#ifdef DEBUG\nstatic void debug(void) { show(); }\n#endif\n"
     "int main(void) { show(); return 0; }\n", 3),
])
def test_conditional_code_after_program_code_is_rejected(source, line):
    result = generate(GenerationRequest(source, ShapeSpec("cat"), program_mode=True))

    assert result.status.value == "FAILED"
    assert result.diagnostics[0].code.value == "UNSUPPORTED_SOURCE"
    assert result.diagnostics[0].line == line
    assert "conditional block" in result.diagnostics[0].message


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_directive_only_conditionals_may_follow_program_code():
    source = """#ifdef _WIN32
#include <windows.h>
#endif
#include <stdio.h>
static int one(void) { return 1; }
#ifndef LIMIT
#define LIMIT 3
#endif
int main(void) { printf("%d\\n", LIMIT + one()); return 0; }
"""

    result = generate(GenerationRequest(source, ShapeSpec("circle"), program_mode=True))

    assert result.status.value == "OK", result.diagnostics
    assert "#ifndef LIMIT\n#define LIMIT 3\n#endif\n" in result.rendered.preamble_text


@pytest.mark.skipif(shutil.which("clang") is None, reason="Clang is required")
def test_line_and_clock_macros_do_not_fail_the_expansion_check(tmp_path):
    source = """#include <assert.h>
#include <stdio.h>
static int checked(int value) {
    assert(value > 0);
    return value;
}
int main(void) {
    printf("%d %d %s %s\\n", checked(2), __LINE__ > 0, __DATE__, __TIME__);
    return 0;
}
"""

    result = generate(GenerationRequest(source, ShapeSpec("cat"), program_mode=True))

    assert result.status.value == "OK", result.diagnostics
    assert result.verification.token_status.value == "PASS"
    assert result.verification.compile_status.value == "PASS"
    generated = tmp_path / "generated.c"
    generated.write_text(result.rendered.source_text, encoding="utf-8")
    binary = tmp_path / "generated"
    subprocess.run(["clang", "-std=c11", str(generated), "-o", str(binary)], check=True)
    assert subprocess.run([str(binary)], capture_output=True, text=True,
                          check=True).stdout.startswith("2 1 ")


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
