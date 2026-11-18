# Code Art Studio

English · [简体中文](README.zh-CN.md)

Reformat one self-contained C11 function into a circle, a cat head or hollow
CODE while preserving effective tokens. Python implements the pipeline,
libclang checks source structure and lexical boundaries, and Clang compiles
the output. Token, geometry, compile and behavior checks are reported separately.

## Install

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

Production use only needs `requirements.txt`. Development dependencies add
pytest. Record the output of `python -m codeart.environment` with any bug
report. CI runs the pure-Python tests in a fast `unit` job on ubuntu-latest on
every trigger, and everything else in a `full` job that also runs on
ubuntu-latest with Python 3.12, Clang 18, libclang 18.1.1 and pytest 9.2.0. The
`full` job runs on pushes to main, on `v*` tags and on every pull request;
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
| Owner completion sheets | Versioned separately | [Reports index](docs/reports/README.md) |

Reproduce acceptance with the command below and inspect `report.json`:
`passed` combines the fixed matrix and scaled-cat checks. The acceptance
CLI exit code alone describes the fixed matrix. Archived reports retain the
results of their original commit, including earlier NOT_RUN states.

## Local web interface

```sh
python -m codeart.app
```

Open **http://127.0.0.1:8765**. Use `--port 8766` if that port is occupied.

1. Choose one of the six built-in functions, open a `.c` file, or paste a function.
2. Select circle, cat or hollow CODE and an initial scale from 1 to 4.
3. Generate and inspect the original source, artwork, actual grid size, scale,
   attempts, coverage, elapsed time and four independent check results.
4. Review diagnostics and layout history. Download the source or JSON report.
5. Use Cancel while a generation is running. Completed results are retained.

The application binds to loopback and processes one generation at a time.
Closing its terminal with Ctrl+C requests cancellation and shuts it down.
It retains the latest five runs in memory. Downloads must be saved before
those runs are evicted or the server is stopped.

Preview uses bundled Roboto Mono Regular with cell height equal to two
character widths, matching B's 0.5 aspect ratio. Space and LF characters are
preserved and long lines scroll horizontally. Font provenance and its SIL
Open Font License are documented in [the app module guide](docs/modules/app.md).

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

Input is one self-contained C11 function using printable ASCII. Parameters,
local variables (including `static` and `static const`), `__func__` and
recursion are supported. External declarations, preprocessing dependencies,
line splicing, trigraphs and real tabs inside tokens are rejected. Predefined
macro names such as `__LINE__`, `__FILE__` and `__COUNTER__` are rejected by
name even without a directive, and
GNU extension keywords such as `__asm__` are outside the frozen scope.
See [source analysis](docs/modules/source.md).

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
See [the verification guide](docs/modules/verify.md) and
[the updated F integration evidence](docs/reports/F_after_E.md).
The [automatic growth demonstration](docs/reports/README.md#automatic-growth-demonstration)
shows how to reproduce and inspect layout retries.

## Team integration and delivery

[Shared contracts](docs/modules/contracts.md) define A–F entry points,
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

GitHub Actions runs three jobs. `Fast pure-Python checks (ubuntu)` uses
ubuntu-latest with a five minute timeout and runs the pure-Python test files
without libclang. `Full checks (ubuntu, clang + node)` is the baseline full
suite: it uses ubuntu-latest with a fifteen minute timeout, installs `clang-18`
plus `requirements-dev.txt`, logs the compiler version and the environment
report, checks the browser script with `node --check`, rejects a decrease in
the collected test count relative to the base revision and runs the whole
suite. `Full checks (macOS, manual or macos-ci label)` repeats the same steps on
macos-15, with a thirty minute timeout, for the cases where Apple Clang matters.

macOS hosted capacity is the scarce resource: runners were frequently
unavailable for more than fifteen minutes and pushes to `main` ended cancelled,
which turned the trunk red although nothing was wrong with the code. The trunk
therefore runs the baseline full suite on ubuntu, and macOS is no longer part of
the default signal.

| Event | ubuntu fast checks | ubuntu full checks | macOS full checks |
| --- | --- | --- | --- |
| Pull request opened, updated or reopened | yes | yes | skipped |
| Pull request labelled `macos-ci` | yes | yes | yes |
| Push to `main` | yes | yes | skipped |
| Push of a `v*` tag | yes | yes | skipped |
| Manual `Run workflow` | yes | yes | yes |

Every pull request runs both Ubuntu jobs. Add the `macos-ci` label to also run
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

See [docs/references.md](docs/references.md) for the creative background
(IOCCC, donut.c), the GCC/Clang tokenization references, the bundled Roboto
Mono font and its OFL license, and the runtime/test dependencies. The donut.c
entry is inspiration only; no code, math, or rendering path is reused.

## Clang and libclang troubleshooting

**Compiler not found.** The Clang command-line compiler and the Python
libclang package are separate dependencies. On macOS, install Apple's tools
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

See [F's delivery follow-up](docs/reports/F_delivery.md) and
[the original completion checklist](docs/reports/F_acceptance.md).

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
informational only: it does not affect verification or layout. Below 10%,
it displays `Token density is low; filler comments occupy most allowed cells.`
It gives no size advice.
