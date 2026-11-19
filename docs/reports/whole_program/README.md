# Whole-program acceptance samples

Three complete, assignment-style C programs run through whole-program mode with
each shape. They are public stand-ins for real coursework: a task manager with
a linked list, Chinese strings and `assert`; a grade report using `qsort` and
a table of `const char *`; and a word counter with a recursive quicksort and
`<ctype.h>`. Every program compiles cleanly with
`clang -std=c11 -pedantic-errors -Wall -Wextra`.

| Commit | Inputs | Expected | Status |
| --- | --- | --- | --- |
| `44c48e7` (clean) | [`input/`](input/), with stdin in [`stdin/`](stdin/) | Token, geometry and compile PASS; behavior `NOT_RUN (NO_FIXTURE)`; the generated program prints exactly what the original prints | PASS (9/9) |

The tool never runs user code, so behavior was compared outside it: the
original and each generated program were built with
`clang -std=c11 -pedantic-errors`, fed the same file from `stdin/`, and their
output compared byte for byte with `stdin/<program>.expected.txt`. All nine
matched, with exit status 0.

| Program | Shape | Canvas | Token | Geometry | Compile | Behavior | Coverage | Lowest ear |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| [`task_manager`](input/task_manager.c) (185 lines) | [cat](output/task_manager_cat.c) | 108 × 54 | PASS | PASS | PASS | NOT_RUN | 94.02% | 92.5% |
| | [circle](output/task_manager_circle.c) | 92 × 46 | PASS | PASS | PASS | NOT_RUN | 95.61% | — |
| | [code](output/task_manager_code.c) | 178 × 32 | PASS | PASS | PASS | NOT_RUN | 88.71% | — |
| [`grade_stats`](input/grade_stats.c) (76 lines) | [cat](output/grade_stats_cat.c) | 74 × 37 | PASS | PASS | PASS | NOT_RUN | 90.91% | 88.2% |
| | [circle](output/grade_stats_circle.c) | 66 × 33 | PASS | PASS | PASS | NOT_RUN | 92.36% | — |
| | [code](output/grade_stats_code.c) | 178 × 32 | PASS | PASS | PASS | NOT_RUN | 81.15% | — |
| [`word_freq`](input/word_freq.c) (85 lines) | [cat](output/word_freq_cat.c) | 66 × 33 | PASS | PASS | PASS | NOT_RUN | 91.83% | 88.8% |
| | [circle](output/word_freq_circle.c) | 64 × 32 | PASS | PASS | PASS | NOT_RUN | 90.20% | — |
| | [code](output/word_freq_code.c) | 178 × 32 | PASS | PASS | PASS | NOT_RUN | 79.01% | — |

Each output has a JSON report beside it with the same name. Each generation
took 1.3–2.0 s end to end. Environment: Linux x86_64, Python 3.13, Ubuntu
Clang 18.1.3, libclang Python bindings 18.1.8.

## What the samples caught

The first run of `task_manager` at `e314ebd` failed the token check:
`assert(list->count > 0)` became `list->count>0` in the artwork, and `assert`
stringizes its argument, so the expanded message text differed. `44c48e7`
compares expanded string literals without whitespace (see the
[verification guide](../../modules/verify.md#checks-and-report-fields)). The
CODE shape's coverage is below the 85% fixed-fixture threshold for two
programs; see the
[whole-program note on item 12](../E_verify.md#whole-program-budgets-and-coverage).

## Reproduce

From the repository root, with Clang and the libclang bindings available:

```sh
W=docs/reports/whole_program
out=$(mktemp -d)
for p in task_manager grade_stats word_freq; do
  for s in cat circle code; do
    python -m codeart.cli --program "$W/input/$p.c" --shape "$s" \
      --output "$out/${p}_$s.c" --report "$out/${p}_$s.json"
    clang -std=c11 -pedantic-errors "$out/${p}_$s.c" -o "$out/${p}_$s"
    "$out/${p}_$s" < "$W/stdin/$p.txt" | cmp - "$W/stdin/$p.expected.txt"
  done
done
```
