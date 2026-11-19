"""A's input limits, lexical boundaries and diagnostic locations.

These tests use the real libclang child, so they run in the macOS CI job that
installs `requirements-dev.txt`. Each case asserts the shared `ErrorCode` and
the reported one-based source position, not just a message string.
"""

import subprocess

import pytest

from codeart import source
from codeart.contracts import (
    CompilerInfo, ErrorCode, StageError, Token, VerificationProfile,
)

SIMPLE = "int f(void) { return 0; }"


def failure(text, profile=None):
    with pytest.raises(StageError) as exc:
        source.analyze_source(text, profile)
    return exc.value.diagnostic


@pytest.mark.parametrize("name", [
    "__FILE__", "__LINE__", "__DATE__", "__TIME__", "__TIMESTAMP__", "__COUNTER__",
    "__INCLUDE_LEVEL__", "__BASE_FILE__", "__STDC__", "__STDC_VERSION__",
    "__STDC_HOSTED__", "__GNUC__", "__clang__", "__has_include",
])
def test_predefined_macro_table_needs_no_directive(name):
    diagnostic = failure(f"int f(void) {{ return {name}; }}")
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert diagnostic.stage == "analysis"
    assert (diagnostic.line, diagnostic.column) == (1, 22)
    assert name in diagnostic.message


@pytest.mark.parametrize("name", ["__INT_MAX__", "__SIZEOF_INT__", "__BYTE_ORDER__"])
def test_implementation_macros_are_rejected(name):
    diagnostic = failure(f"int f(void) {{ return {name}; }}")
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == (1, 22)


@pytest.mark.parametrize("text", [
    'int f(void) { return "__LINE__ __FILE__"[0]; }',
    "int f(void) { /* __LINE__ __FILE__ */ return 0; }",
    "int f(void) { // __COUNTER__\nreturn 0; }",
])
def test_macro_names_in_literals_and_comments_are_allowed(text):
    model = source.analyze_source(text)
    assert model.function_name == "f"


@pytest.mark.parametrize("text", [
    'int f(void) { __asm__("nop"); return 0; }',
    'int f(void) { __attribute__((unused)) int x = 1; return x; }',
    'int f(void) { __extension__ int x = 1; return x; }',
    'int f(void) { __int128 x = 1; return (int)x; }',
    'int f(void) { __thread int x = 1; return x; }',
])
def test_compiler_extensions_are_rejected(text):
    diagnostic = failure(text)
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == (1, 15)


def test_extension_names_used_as_identifiers_stay_legal():
    model = source.analyze_source("int f(void) { int typeof = 1; return typeof; }")
    assert model.function_name == "f"


@pytest.mark.parametrize("name", ["__FUNCTION__", "__PRETTY_FUNCTION__", "__FUNCSIG__"])
def test_function_name_extensions_are_rejected(name):
    diagnostic = failure(f"int f(void) {{ return {name}[0]; }}")
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == (1, 22)


def test_non_ascii_reports_the_source_position():
    diagnostic = failure("int f(void) {\n  return 变量;\n}")
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == (2, 10)


@pytest.mark.parametrize("char", ["\x00", "\x01", "\x0b", "\x7f", "\u00e9"])
def test_control_and_delete_characters_are_rejected(char):
    diagnostic = failure(f"int f(void) {{ return {char}; }}")
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == (1, 22)


def test_tabs_are_allowed_outside_tokens_only():
    assert source.analyze_source("int\tf(void)\t{ return\t0; }").function_name == "f"
    diagnostic = failure('int f(void) { return "a\tb"[0]; }')
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == (1, 22)


@pytest.mark.parametrize("text,position", [
    ("int f(void) { return 1 ??= 2; }", (1, 24)),
    ("int f(void) { return 1 ??( 2; }", (1, 24)),
    ("int f(void) { ret\\\nurn 0; }", (1, 18)),
    ("int f(void) {\r\n ret\\\r\nurn 0; }", (2, 5)),
    ("int f(void) {\r ret\\\nurn 0; }", (2, 5)),
    ("int f(void) {\r\n\r  ??= invalid; }", (3, 3)),
])
def test_line_splicing_and_trigraphs_report_positions(text, position):
    diagnostic = failure(text)
    assert diagnostic.code == ErrorCode.UNSUPPORTED_SOURCE
    assert (diagnostic.line, diagnostic.column) == position


def test_crlf_is_normalized_but_positions_are_original():
    text = "/* header */\r\nint f(void)\r\n{\r\n  return 0;\r\n}\r\n"
    model = source.analyze_source(text)
    assert model.original_source == text
    assert "\r" not in model.normalized_source
    assert len(model.original_comments) == 1
    assert (model.tokens[0].source_line, model.tokens[0].source_column) == (2, 1)


def test_lone_cr_is_normalized():
    model = source.analyze_source("int f(void)\r{ return 0; }\r")
    assert "\r" not in model.normalized_source
    assert model.function_name == "f"


def test_object_compile_failure_keeps_compiler_location(monkeypatch):
    stderr = "/tmp/build/input.c:3:5: error: static assertion failed\n"

    class FakeBuilds:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def compiler_info(self, profile, ctx):
            return CompilerInfo("/usr/bin/clang", "clang", profile.flags, ())

        def build(self, *args, **kwargs):
            raise source.BuildFailed(
                subprocess.CompletedProcess(args, 1, "", stderr)
            )

    monkeypatch.setattr(source, "BuildSession", FakeBuilds)
    diagnostic = failure(SIMPLE)
    assert diagnostic.code == ErrorCode.INVALID_SOURCE
    assert (diagnostic.line, diagnostic.column) == (3, 5)
    assert diagnostic.details["stderr"] == stderr


@pytest.mark.parametrize("stderr,expected", [
    ("/tmp/x/input.c:12:4: error: expected ';'\n", (12, 4)),
    ("input.c:1:1: fatal error: 'nope.h' file not found\n", (1, 1)),
    ("clang: error: no input files\n", (None, None)),
    ("", (None, None)),
])
def test_first_compiler_error_parsing(stderr, expected):
    assert source._first_compiler_error(stderr) == expected


def tokens(*pairs):
    return [Token(index, kind, spelling, len(spelling), 1, 1)
            for index, (kind, spelling) in enumerate(pairs)]


@pytest.mark.parametrize("pairs,expected", [
    ((("IDENTIFIER", "f"), ("PUNCTUATION", "(")), True),
    ((("IDENTIFIER", "a"), ("PUNCTUATION", ")")), True),
    ((("PUNCTUATION", ")"), ("PUNCTUATION", "{")), True),
    ((("PUNCTUATION", "*"), ("PUNCTUATION", "/")), True),
    ((("IDENTIFIER", "a"), ("IDENTIFIER", "b")), False),
    ((("PUNCTUATION", "+"), ("PUNCTUATION", "+")), False),
    ((("PUNCTUATION", "/"), ("PUNCTUATION", "/")), False),
    ((("PUNCTUATION", "/"), ("PUNCTUATION", "*")), False),
    ((("PUNCTUATION", "<"), ("PUNCTUATION", "<")), False),
    ((("PUNCTUATION", "-"), ("PUNCTUATION", ">")), False),
    ((("NUMERIC_LITERAL", "1"), ("PUNCTUATION", ".")), False),
    ((("IDENTIFIER", "L"), ("STRING_LITERAL", '"a"')), False),
])
def test_can_join_uses_the_whole_run(pairs, expected):
    run = tokens(*pairs)
    assert source.can_join(run[:-1], run[-1], VerificationProfile()) is expected


@pytest.mark.parametrize("pairs", [
    (("PUNCTUATION", "."), ("PUNCTUATION", "."), ("PUNCTUATION", ".")),
    (("PUNCTUATION", "?"), ("PUNCTUATION", "?"), ("PUNCTUATION", "(")),
    (("PUNCTUATION", "/"), ("PUNCTUATION", "*")),
    (("LITERAL", "0x1p"), ("PUNCTUATION", "+")),
    (("IDENTIFIER", "数"), ("IDENTIFIER", "量")),
])
def test_can_join_checks_the_suffix_after_a_delimiter(pairs):
    run = tokens(("IDENTIFIER", "name"), ("PUNCTUATION", ";"), *pairs)
    assert source.can_join(run[:-1], run[-1], checked_run=True) is False


# Short spellings that join into longer C tokens, plus the delimiters that the
# incremental check treats as boundaries.
_JOIN_POOL = (
    ".", "+", "-", ">", "<", "=", "/", "*", "?", ":", "%", "&", "|", "!",
    "(", ")", "[", "]", "{", "}", ",", ";",
    "a", "L", "u8", "e", "x", "1", "0", "0x1p", "1e", '"s"', "'c'",
)


def _lex_alone(spelling):
    reply = source._join_worker.request(
        {"mode": "lex", "text": spelling, "flags": list(VerificationProfile().flags)},
        VerificationProfile().lex_timeout,
    )
    (token,) = reply["tokens"]
    return token["kind"], token["spelling"]


def test_default_can_join_matches_a_full_relex_of_every_run():
    import random

    rng = random.Random(58)
    kinds = dict(_lex_alone(spelling)[::-1] for spelling in _JOIN_POOL)
    full_check = source._can_join_cached.__wrapped__
    flags = tuple(VerificationProfile().flags)
    timeout = VerificationProfile().lex_timeout
    fixed = (
        ("?", "?", "("), ("?", "?", ")"), ("a", "?", "?", "("), (";", "?", "?", ")"),
        (".", ".", "."), ("/", "*"), ("/", "/"), ("+", "+"), ("-", ">"), ("<", "<", "="),
        ("L", '"s"'), ("u8", '"s"'), ("1", "e", "+"), ("0x1p", "+"), ("a", ";", "1", "e"),
        ("%", ":", "%", ":"), ("<", ":"), (":", ">"), ("<", "%"),
    )
    spellings = [*fixed, *(rng.choices(_JOIN_POOL, k=rng.randint(2, 7)) for _ in range(600))]
    for chosen in spellings:
        pairs = [(kinds[spelling], spelling) for spelling in chosen]
        run = tokens(*pairs)
        # Grow the run the way the layout does, and keep going past a refusal
        # because public callers may ask about any run.
        for end in range(2, len(run) + 1):
            expected = full_check(tuple(pairs[:end]), flags, timeout)
            assert source.can_join(run[:end - 1], run[end - 1]) is expected, pairs[:end]


def test_three_dots_and_empty_run():
    run = tokens(("PUNCTUATION", "."), ("PUNCTUATION", "."), ("PUNCTUATION", "."))
    assert source.can_join(run[:-1], run[-1], VerificationProfile()) is False
    assert source.can_join([], run[0], VerificationProfile()) is True


def test_empty_spelling_is_a_programming_error():
    run = tokens(("IDENTIFIER", "a"))
    with pytest.raises(ValueError):
        source.can_join(run, Token(9, "IDENTIFIER", "", 0, 1, 1), VerificationProfile())


def test_missing_compiler_is_a_dependency_diagnostic():
    diagnostic = failure(SIMPLE, VerificationProfile(compiler="definitely-not-a-compiler"))
    assert diagnostic.code == ErrorCode.DEPENDENCY_UNAVAILABLE
    assert diagnostic.stage in {"analysis", "setup"}
