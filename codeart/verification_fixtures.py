"""The v1.4 builtin C sources and their fixed behavior inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType

from .procutil import BuildSession


@dataclass(frozen=True)
class BuiltinFixture:
    name: str
    signature: str
    source: str
    cases: tuple[tuple[int, ...], ...]

    def wrapper(self) -> str:
        # Put headers after the function so their macros cannot affect it.
        calls = "".join(
            f'    printf("%d\\n", {self.name}({", ".join(map(str, case))}));\n'
            "    fflush(stdout);\n"
            for case in self.cases
        )
        return (
            "\n#include <limits.h>\n#include <stdio.h>\n"
            '_Static_assert(sizeof(int) * CHAR_BIT == 32 && INT_MAX == 2147483647, '
            '"32-bit int required");\n'
            "int main(void) {\n"
            f"{calls}    return 0;\n"
            "}\n"
        )


def _fixture(name, parameters, body, cases):
    signature = f"int {name}({parameters})"
    return BuiltinFixture(name, signature, f"{signature} {{\n{body}\n}}\n", cases)


_PAIRS = ((0, 0), (-1, 1), (1, -1), (7, 7), (-10, -3), (-3, -10),
          (1000, -1000), (-1000, 1000))

BUILTIN_FIXTURES = MappingProxyType({
    fixture.name: fixture
    for fixture in (
        _fixture("max2", "int a, int b", "    return a > b ? a : b;", _PAIRS),
        _fixture("min2", "int a, int b", "    return a < b ? a : b;", _PAIRS),
        _fixture(
            "clamp", "int x, int lo, int hi",
            "    return x < lo ? lo : x > hi ? hi : x;",
            ((-5, 0, 10), (0, 0, 10), (5, 0, 10), (10, 0, 10), (15, 0, 10),
             (-5, -10, -1), (3, 3, 3), (-1000, -1000, 1000)),
        ),
        _fixture("absdiff", "int a, int b", "    return a > b ? a - b : b - a;", _PAIRS),
        _fixture(
            "gcd", "int a, int b",
            "    while (b != 0) {\n"
            "        int remainder = a % b;\n"
            "        a = b;\n"
            "        b = remainder;\n"
            "    }\n"
            "    return a;",
            ((0, 0), (0, 5), (5, 0), (1, 1), (12, 18), (17, 13), (100, 25),
             (10000, 9999)),
        ),
        _fixture(
            "sum_to_n", "int n", "    return n * (n + 1) / 2;",
            tuple((n,) for n in (0, 1, 2, 3, 10, 99, 100, 1000)),
        ),
    )
})


@dataclass(frozen=True)
class FixtureSelection:
    """Explicit selection made by the builtin sample entry point."""

    fixture: BuiltinFixture
    _builds: BuildSession | None = field(default=None, repr=False, compare=False)


def select_builtin(name: str) -> FixtureSelection:
    return FixtureSelection(BUILTIN_FIXTURES[name])
