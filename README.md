# Code Art Studio

English · [简体中文](https://github.com/nukofish/ascii-art-executable/blob/main/README.zh-CN.md)

Paste or open a complete C11 program and arrange it as a circle, a cat head
or hollow CODE. Copy or download the resulting `.c` file. The layout starts
with the program's own tokens and distributes short filler comments using
space left in the selected canvas. Single-function input, function extraction
and built-in samples are also available.

libclang checks token preservation and Clang compiles the result. The app
reports token, geometry, compile and behavior checks separately.

```sh
pip install code-art-studio
codeart --program hello.c --shape cat --output hello_cat.c
```

## Why

Shaped source code is a long tradition, from the obfuscated programs of the
IOCCC to banners of code printed on T-shirts. Making one by hand takes hours:
every token has to move, and a single misplaced `+` next to another `+`
silently becomes `++`. Most people give up, or produce a picture that no
longer compiles. We wanted a tool that does the tedious part, so that a
student can turn their own assignment into a cat in seconds and still hand in
a program that behaves exactly the same.

## What is new

Existing tools solve neighbouring problems, but not this one:

| Tool | What it does | What it does not do |
| --- | --- | --- |
| Text banner tools such as `pyfiglet` or `art` | Draw letters out of characters | The output is a picture, not a program |
| Image-to-ASCII converters | Turn a photo into characters | Same: nothing compiles |
| Formatters such as `clang-format` or `black` | Re-indent real code | Keep the code's own shape; cannot draw a cat |
| Hand-made IOCCC entries | Shaped programs that run | Take hours of manual work per program |

Code Art Studio combines the last two: it reshapes a real, complete C11
program automatically, and then proves the result is still the same program.

- **Token-exact layout.** libclang splits the program into tokens. Two tokens
  are placed side by side only when Clang reads them back as the same two
  tokens, so `a + +b` never turns into `a ++b`, and `??(` is never formed.
- **Independent verification.** After layout, the result is lexed, measured
  and compiled again: the token sequence and the preprocessed macro
  expansion must match the original exactly, the code must stay inside the
  shape, and the program must compile and link. Built-in samples are also run
  and must return the same values.
- **Whole programs, not just snippets.** `#include`, `#define` and
  conditional blocks stay above the artwork; everything else, including
  Chinese text in strings and identifiers, is arranged inside the shape. The
  program's own comments are dropped, and short filler comments fill the empty
  cells.
- **Three ways to use it.** A command-line tool, a local web page, and a
  Python API for notebooks, on Linux, macOS and Windows.

## Use cases

- **Teaching C.** Show students that whitespace and line breaks are not part
  of a C program's meaning, and that tokens are. The verification report
  explains exactly which token would change if two were joined.
- **Course projects and demos.** Turn a finished assignment into a poster or a
  slide that still compiles, for example a cat-shaped grade calculator.
- **Programming clubs and contests.** Produce IOCCC-style shaped entries as a
  starting point, then refine them by hand.
- **Testing C tools.** Generated files are unusual but valid C11, which makes
  them good inputs for checking that formatters, linters and compilers handle
  odd layouts.

## Quick start

Install from PyPI. You also need a C11 `clang` on PATH (see
[Install](#install) for each operating system):

```sh
pip install code-art-studio
clang --version
```

Arrange a complete program and compile the result:

```sh
codeart --program hello.c --shape cat --output hello_cat.c --report hello_cat.json
clang -std=c11 hello_cat.c -o hello_cat && ./hello_cat
```

Start the local web interface (open http://127.0.0.1:8765):

```sh
codeart-web
```

Use it from Python or a Jupyter notebook:

```python
from codeart.contracts import GenerationRequest, ShapeSpec
from codeart.pipeline import generate

source = open("hello.c", encoding="utf-8").read()
result = generate(GenerationRequest(source, ShapeSpec("cat"), program_mode=True))
print(result.status.value)          # OK when every required check passed
print(result.rendered.source_text)  # the arranged program
```

In a notebook the command line works too: `!codeart --program hello.c --shape cat`.
[`examples/demo.ipynb`](https://github.com/nukofish/ascii-art-executable/blob/main/examples/demo.ipynb) walks through all three shapes.
The web interface only listens on 127.0.0.1, so on a remote JupyterHub use the
command line or the Python API. `codeart` is the same as `python -m codeart.cli`,
and `codeart-web` is the same as `python -m codeart.app`.

## Install

To use the tool, `pip install code-art-studio` is enough once a C11 Clang
compiler is installed. The steps below set up a development checkout.

Use Python 3.10 or later and a C11 Clang compiler. The pinned libclang Python
package includes its native library. On macOS, install Apple's command-line
developer tools if `clang --version` is unavailable. On Ubuntu 24.04, install
`clang-18` and put `/usr/lib/llvm-18/bin` on PATH.

From the repository root on macOS or Linux:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m codeart.environment
python -m pytest -q
```

On Windows, Clang uses the MSVC headers and linker, so Visual Studio or its
Build Tools with the C++ desktop workload is also required. The same steps in
PowerShell, with tested versions and common problems, are in
[Running on Windows](https://github.com/nukofish/ascii-art-executable/blob/main/docs/windows.md).

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass -Force
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m codeart.environment
python -m pytest -q
```

Production use only needs `requirements.txt`. Development dependencies add
pytest. Record the output of `python -m codeart.environment` with any bug
report. CI runs the pure-Python tests in a fast `unit` job on ubuntu-latest on
every trigger, and everything else in a `full` job that also runs on
ubuntu-latest with Python 3.12, Clang 18, libclang 18.1.1 and pytest 9.2.0. The
`full` job runs on pushes to main, on `v*` tags and on every pull request.
A `full-windows` job runs on the same events on windows-latest;
macOS is covered by a separate `full-macos` job that only runs on manual
dispatch or on a `macos-ci` label. See
[continuous integration](#continuous-integration). Local
validation also uses macOS, Python 3.14 and Apple Clang. The exact local
versions are available in the environment report.

## Status

The `0c80b7b` baseline passed 328 tests, all 18 fixed-size cases and
144 behavior comparisons, plus the cat checks at 1x, 2x and 4x. [The Ubuntu
full CI run on main@0c80b7b](https://github.com/nukofish/ascii-art-executable/actions/runs/42843452033)
also passed the full suite; that run did not execute production acceptance. Later commits have their own CI logs and versioned evidence.

| Check or delivery | Status | Evidence or interpretation |
| --- | --- | --- |
| Fixed h32 matrix | PASS on the baseline | 18 outputs; token, geometry, compile and behavior checked |
| Built-in behavior | PASS on the baseline | 144 actual comparisons |
| Cat h32/h64/h128 | PASS on the baseline | B references loaded by E |
| Custom-source behavior | NOT_RUN by design | NO_FIXTURE |
| Behavior above the size limit | NOT_RUN by resource policy | OUTPUT_TOO_LARGE |
| Current CI | See the current run | [Actions](https://github.com/nukofish/ascii-art-executable/actions/workflows/tests.yml) |
| Owner completion sheets | Versioned separately | [Reports index](https://github.com/nukofish/ascii-art-executable/blob/main/docs/reports/README.md) |

Reproduce acceptance with the command below and inspect `report.json`:
`passed` combines the fixed matrix and scaled-cat checks. The acceptance
CLI exit code alone describes the fixed matrix. Archived reports retain the
results of their original commit, including earlier NOT_RUN states.

## Local web interface

```sh
python -m codeart.app
```

Open **http://127.0.0.1:8765**. Use `--port 8766` if that port is occupied.

1. Choose one of the six built-in functions, or open or paste C source.
2. Select circle, cat or hollow CODE and an initial scale from 1 to 4.
3. **Arrange a complete C program** is selected by default. Preprocessor
   directives and complete conditional blocks stay above the artwork,
   separated by two blank lines.
4. Generate and inspect the original source, artwork, actual grid size, scale,
   attempts, coverage, elapsed time and four independent check results.
5. Use **Copy code** or download the complete source. Diagnostics, layout
   history and a JSON report are also available.
6. Use Cancel while a generation is running. Completed results are retained.

The application binds to loopback and processes one generation at a time.
Closing its terminal with Ctrl+C requests cancellation and shuts it down.
It retains the latest five runs in memory. Downloads must be saved before
those runs are evicted or the server is stopped.
The web app does not execute user programs. Custom program behavior checks are
`NOT_RUN`, so run the downloaded program manually to compare its behavior.

The artwork preview fits the available space and keeps lines and holes aligned.
Wide characters use two cells. The preview uses bundled Roboto Mono Regular
and system fallback fonts for missing glyphs. See the [app module guide](https://github.com/nukofish/ascii-art-executable/blob/main/docs/modules/app.md).

## Command line

Run and behavior-test an unchanged built-in sample:

```sh
python -m codeart.cli --sample max2 --shape cat --scale 1.5 \
  --output max2_cat.c --report max2_cat.json
```

Compile and verify an ordinary function:

```sh
python -m codeart.cli --source example.c --shape circle --output generated.c
```

Arrange and write a complete C program:

```sh
python -m codeart.cli --program task_manager.c --shape cat \
  --output task_manager_art.c --report task_manager_art.json
```

Whole-program mode moves preprocessor directives and complete conditional
regions to the output prefix, then arranges the remaining source tokens
together in order. Verification compares preprocessed tokens and compiles the
final translation unit, linking it when it defines `main`. User code is not
executed, so behavior is `NOT_RUN (NO_FIXTURE)`. If moving directives changes
macro expansion, token verification fails instead of marking the output valid.
Relative local header files are not currently resolved in whole-program mode.
Directives must be safely movable. A conditional block (`#if`/`#ifdef`) that
contains code is only accepted before the first declaration; one inside a
function body or after earlier code is rejected at its `#if` line, as is an
`#undef` after code. Programs may use `assert`, `__LINE__` and the date and
time macros; line numbers they report refer to the generated program, and
text produced by stringizing (`#x`, such as an `assert` message) uses the
generated program's spacing.

The sample choices are `max2`, `min2`, `clamp`, `absdiff`, `gcd` and
`sum_to_n`. Each includes eight fixed behavior inputs. Ordinary source and
edited samples have behavior `NOT_RUN` with reason `NO_FIXTURE`. A matching
function name alone does not select an executable fixture.

Exit status is nonzero for failed checks or pipeline diagnostics. A custom
function can succeed with behavior `NOT_RUN` when token, geometry and compile
checks pass. Output and diagnostics use stdout and stderr respectively.
Use a separate file for `--report` so it cannot overwrite the source input
or the generated C file.
The earlier `--demo` option remains a fixed smoke fixture with simulated
A/C/D/E stages and explicit `NOT_RUN` checks.

## Supported input and verification

Complete-program mode accepts UTF-8 C source with Chinese characters in
strings, identifiers and the preprocessor prefix. Wide characters occupy two
grid cells. Empty parameter lists such as `int main()` are accepted as written.

Single-function mode takes one self-contained C11 function using printable ASCII. Parameters,
local variables (including `static` and `static const`), `__func__` and
recursion are supported. External declarations, preprocessing dependencies,
line splicing, trigraphs and real tabs inside tokens are rejected. Predefined
macro names such as `__LINE__`, `__FILE__` and `__COUNTER__` are rejected by
name even without a directive, and
GNU extension keywords such as `__asm__` are outside the frozen scope.
See [source analysis](https://github.com/nukofish/ascii-art-executable/blob/main/docs/modules/source.md).

The verification evidence supports token preservation, C11 compilation and
matching behavior on the specified sample inputs. A skipped check is shown
as `NOT_RUN` with a reason. Geometry failures keep the run from being shown
as verified. Behavior is skipped for canvases above the configured cell limit.

## Fixed-size acceptance

E's public command archives the six-function by three-shape matrix.

```sh
python -m scripts.run_verification --output-dir docs/reports/local-check/fixed
```

Use a new directory for each run. The report identifies the commit and
worktree state, records 18 h32 outputs and counts actual behavior comparisons.
The same run checks the cat mask against B's h32/h64/h128 reference files.
`cat_scales` records each scale's result. `passed` combines the fixed matrix
and all three scale checks. The exit code still reports the fixed matrix.
See [the verification guide](https://github.com/nukofish/ascii-art-executable/blob/main/docs/modules/verify.md) and
[the updated F integration evidence](https://github.com/nukofish/ascii-art-executable/blob/main/docs/reports/F_after_E.md).
The [automatic growth demonstration](https://github.com/nukofish/ascii-art-executable/blob/main/docs/reports/README.md#automatic-growth-demonstration)
shows how to reproduce and inspect layout retries.

## Team integration and delivery

Releases are published to PyPI from GitHub releases; see
[Publishing to PyPI](https://github.com/nukofish/ascii-art-executable/blob/main/docs/publishing.md).

[Shared contracts](https://github.com/nukofish/ascii-art-executable/blob/main/docs/modules/contracts.md) define A–F entry points,
coordinates, error codes and injected dependencies. Call
`codeart.pipeline.generate(request, deps=..., cancel_event=...)`.
Production dependencies load automatically. Test doubles use the same signatures.

Each module owner maintains normal and boundary tests and its English module
guide. E owns the full regression evidence and independent scaled-cat
references supplied by B. F owns the app, CLI, environment setup and run
instructions. Formal reports should record inputs, command, expected result,
actual result, evidence and status. Store agreed deliverables under
`docs/reports/`, using `case_<function>_<shape>_h<rows>_s<scale>.c` for source artifacts.
Keep fixed and grown runs in separate `fixed/` and `scaled/` subdirectories.
Each completion table identifies the tested commit and any uncommitted changes.
Web and CLI reports include that revision information.

### Continuous integration

GitHub Actions runs four jobs. `Fast pure-Python checks (ubuntu)` uses
ubuntu-latest with a five minute timeout and runs the pure-Python test files
without libclang. `Full checks (ubuntu, clang + node)` is the baseline full
suite: it uses ubuntu-latest with a thirty minute timeout, installs `clang-18`
without recommended packages (the downloaded packages are cached per runner
image, because the runner's Ubuntu mirror is sometimes slow) plus
`requirements-dev.txt`, logs the compiler version and the environment
report, checks the browser script with `node --check`, rejects a decrease in
the collected test count relative to the base revision and runs the whole
suite. `Full checks (windows, clang + node)` runs on windows-latest with
Python 3.12, the runner's Clang and a twenty-five minute timeout, in PowerShell.
It runs the whole suite, the fixed acceptance matrix, the whole-program samples
and the command-line tool on a Chinese program; each step runs even when an
earlier one failed, so one run shows every Windows problem.
`Full checks (macOS, manual or macos-ci label)` repeats the same steps on
macos-15, with a thirty minute timeout, for the cases where Apple Clang matters.

macOS hosted capacity is the scarce resource: runners were frequently
unavailable for more than fifteen minutes and pushes to `main` ended cancelled,
which turned the trunk red although nothing was wrong with the code. The trunk
therefore runs the baseline full suite on ubuntu, and macOS is no longer part of
the default signal.

| Event | ubuntu fast checks | ubuntu full checks | Windows full checks | macOS full checks |
| --- | --- | --- | --- | --- |
| Pull request opened, updated or reopened | yes | yes | yes | skipped |
| Pull request labelled `macos-ci` | yes | yes | yes | yes |
| Push to `main` | yes | yes | yes | skipped |
| Push of a `v*` tag | yes | yes | yes | skipped |
| Manual `Run workflow` | yes | yes | yes | yes |

Every pull request runs both Ubuntu jobs and the Windows job. Add the `macos-ci` label to also run
the full suite on macOS; removing that label cancels the pending macOS job and
adding it back queues a fresh run. Recent runs of the same ref are cancelled
when a newer run starts. To run everything by hand, open the **Actions** tab, select the
**Python tests** workflow and choose **Run workflow** on the branch to check.

The ubuntu full job fails rather than silently skipping when the `libclang`
native library cannot be imported, because most of the suite is skipped without
it. The `libclang==18.1.1` wheel bundles the library for Linux, so no extra
system package is normally needed. If `import clang.cindex` ever fails on the
runner, install the system library and point Clang at it:

```sh
sudo apt-get install -y libclang-18-dev
export CLANG_LIBRARY_PATH=/usr/lib/llvm-18/lib/libclang.so.1
```

Add the label for the C analyzer, the Clang or libclang integration, the browser
script or the collected test count. Use `macos-ci` when the change can only be
validated against Apple Clang, such as compiler-flag or Mach-O specific work.

## References

See [docs/references.md](https://github.com/nukofish/ascii-art-executable/blob/main/docs/references.md) for the creative background
(IOCCC, donut.c), the GCC/Clang tokenization references, the bundled Roboto
Mono font and its OFL license, and the runtime/test dependencies. The donut.c
entry is inspiration only; no code, math, or rendering path is reused.

## Clang and libclang troubleshooting

**Compiler not found.** The Clang command-line compiler and the Python
libclang package are separate dependencies. For Windows, see
[Running on Windows](https://github.com/nukofish/ascii-art-executable/blob/main/docs/windows.md#common-problems). On macOS, install Apple's tools
with `xcode-select --install`, then check `clang --version`. On Ubuntu 24.04,
run `sudo apt-get update && sudo apt-get install -y clang-18`, then
`export PATH="/usr/lib/llvm-18/bin:$PATH"`.

**No module named clang, or libclang cannot load.** Run pip with the same
interpreter used to launch the app:

```sh
python -m pip install -r requirements-dev.txt
python -m pip show libclang
python -c "import clang.cindex; clang.cindex.Index.create(); print('libclang loaded')"
```

The project pins `libclang==18.1.1`, including its native library. Apple's
Clang executable does not install this Python package. Avoid adding the
separate `clang` package to the same environment because both packages use
the `clang` import namespace. If an environment has mixed packages, create
a fresh virtual environment and install the requirements there.

**Tests fail in one terminal but work in another.** Compare
`python -m codeart.environment`, `python -m pip --version` and
`clang --version` in both. Check the active virtual environment and PATH.
Attach the version report, exact command, input and diagnostic to the issue.

**A check says NOT_RUN.** Read its reason. `NO_FIXTURE` is expected for
ordinary or edited input. `OUTPUT_TOO_LARGE` skips behavior due to the
configured canvas limit. `DEPENDENCY_UNAVAILABLE` requires fixing the
compiler or library installation; it is not a passing check.

See [F's delivery follow-up](https://github.com/nukofish/ascii-art-executable/blob/main/docs/reports/F_delivery.md) and
[the original completion checklist](https://github.com/nukofish/ascii-art-executable/blob/main/docs/reports/F_acceptance.md).

## Complete-file function extraction / 整份文件提取

`--source` remains the v1.4 single-function path. `--file` is an optional
F-layer convenience: it locates candidate definitions in a complete C file,
runs each candidate through A's real analyzer, and passes only the chosen
function to `generate()`. `generate()` and A still accept exactly one
self-contained function. This was accepted on 2026-11-10 as a v1.5 extension;
the v1.4 acceptance input remains the single-function path, so use
`--sample`/`--source` for v1.4 acceptance runs.

Duplicate eligible names are reported as `AMBIGUOUS_FUNCTION`; use
`--function` only when the name is unique.

```sh
python -m codeart.cli --file example.c --function helper --shape circle --output helper_art.c --report helper_report.json
```

The locator masks comments, literals and directive lines before matching
braces; a `#if`/`#endif` inside a comment or macro body does not change the
result. It normalises CRLF/lone CR and strips a leading UTF-8 BOM. `main` and
functions inside conditional preprocessing regions are ineligible. Omit
`--function` to choose the first passing candidate. Function-pointer and
parenthesised declarators are named by A's `function_name`, not by the
locator's regex. External typedefs, macros, globals and other functions are
not copied. Comments and literals inside the extracted function are retained;
A determines support.

The locator is lexical, not a complete C parser or preprocessor: K&R-style
definitions and some macro-generated declarations may not be listed.
Conditional regions are rejected conservatively. The JSON `prepass` section
records candidates, the selection, ignored line ranges and precise
`ignored_segments` for same-line prefixes/suffixes. It does not claim
whole-program behavior. Custom extractions have no built-in behavior fixture.

In the web interface, enable **Extract from a complete C file**, click **Find
functions**, then select a passing candidate. Failed candidates show A's
original-file diagnostic positions. Generation rechecks the chosen function.
Only the extracted function is verified, not the entire input program.

`code_fill_ratio` is effective non-space token ink divided by allowed cells
(the renderer's token coverage), excluding filler comments. It is
informational only: it does not affect verification or layout. In ordinary
input mode, below 10% it displays
`Token density is low; filler comments occupy most allowed cells.` The warning
applies to either mode. Complete-program mode chooses the canvas from the
source tokens and uses short block comments to distribute spare space when
needed.
