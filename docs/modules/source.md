# Source analysis and lexical boundaries (Part A)

Part A turns user text into the single artifact the rest of the pipeline trusts:
a `SourceModel` with the original text, its LF-normalized copy, the ordered raw
token stream, the original comments and the function signature. It also owns the
`can_join` decision that lets the layout stage place two tokens next to each
other without a separator. Nothing here chooses a shape, a size or a comment.

## Public interface

| Name | Signature | Purpose |
| --- | --- | --- |
| `analyze_source` | `(text, profile=None, *, ctx=None) -> SourceModel` | Validate one self-contained C11 function; raise `StageError` with a shared `Diagnostic` on failure. |
| `analyze_program` | `(text, profile=None, *, ctx=None) -> SourceModel` | Validate a complete C11 translation unit and return its non-directive token stream with preprocessor sections recorded for the output prefix. |
| `can_join` | `(run_tokens, next_token, profile=None, *, checked_run=False) -> bool` | Check whether adjoining tokens preserves their kinds and raw spellings. |
| `lex_source` | `(text, *, ctx) -> tuple[LexedToken, ...]` | Raw token adapter E reuses for the generated source. |
| `prepare_profile` | `(profile) -> VerificationProfile` | Bind A's lexer to the profile so E compares with the same lexer. |

`codeart.source.__all__` contains exactly these five names. Import shared types
from `codeart.contracts`; never import `codeart._source_lexer` or
`codeart._source_worker` from another owner's module.

## Input limits

The single-function entry point accepts one self-contained definition and
does not require `main`. The complete-program entry point accepts a translation
unit with multiple definitions and keeps its directives and conditional
regions in `SourceModel.preamble_text`. Parameters, local variables
(including `static` and `static const`), `__func__`, `goto` labels and
recursion are supported in the arranged token stream. Each rejection uses a
shared `ErrorCode` and, when the position is known, a one-based line and column.

The table below describes the single-function entry point. Complete-program
analysis also accepts directives, multiple definitions, global declarations
and cross-function references. It moves directives and complete conditional
regions into the prefix, then the pipeline compares preprocessed token streams
before compiling the final program. Line splicing is accepted inside a
preserved directive and rejected in arranged source. A `#pragma`, `#line` or
`#undef` after ordinary code is rejected because moving it could change
compiler state or macro scope. A conditional group (`#if`, `#ifdef`,
`#ifndef`) that contains code is only moved when no code comes before it;
later ones, including groups inside a function body, are rejected at the
`#if` line. Moving such code would only be checked for the default macro
configuration and could break a build with other `-D` options. Conditional
groups that contain only directives may appear anywhere.
The file must compile with available headers and dependencies. Macros that
depend on directive placement can still change when moved to the prefix.
Preprocessed token comparison and the final build catch changes to expansion
or compilation.

Complete-program input accepts printable UTF-8 text, including Chinese
identifiers and string literals. Fullwidth and wide characters occupy two
cells. Standalone combining marks and non-printable characters other than
the permitted line endings and tabs are rejected. Original comments are
accepted and treated as whitespace in the artwork. Comments in preserved
preprocessor sections stay with those sections.

Complete-program analysis and compilation use `-Wno-strict-prototypes` so
definitions such as `void ensure_capacity() {}` and `int main() { return 0; }`
are accepted with their original spellings. C syntax errors still fail.

| Input | Result | Location |
| --- | --- | --- |
| Printable ASCII `0x20`–`0x7E`, LF, CRLF, lone CR, tab outside tokens | accepted | – |
| Non-ASCII character or control character (`0x00`–`0x1F`, `0x7F`) | `UNSUPPORTED_SOURCE` | original line and column of the character |
| Real tab inside a token | `UNSUPPORTED_SOURCE` | token start |
| Backslash-newline (line splice) | `UNSUPPORTED_SOURCE` | the backslash |
| Trigraph (`??=` …) | `UNSUPPORTED_SOURCE` | the `?` |
| Preprocessing directive (`#`, `%:`) | `UNSUPPORTED_SOURCE` | the directive token |
| Predefined macro name from the table (`__LINE__`, `__FILE__`, `__COUNTER__`, …) | `UNSUPPORTED_SOURCE` | the identifier |
| Any other implementation macro (`__INT_MAX__`, `__BYTE_ORDER__`, …) | `UNSUPPORTED_SOURCE` | the macro instantiation |
| Function-name extension (`__FUNCTION__`, `__PRETTY_FUNCTION__`, `__FUNCSIG__`) | `UNSUPPORTED_SOURCE` | the identifier |
| GNU extension keyword (`__asm__`, `__attribute__`, `__extension__`, `__int128`, …) | `UNSUPPORTED_SOURCE` | the keyword |
| External function, external object, `extern` declaration | `UNSUPPORTED_SOURCE` | first reference or declaration |
| More than one definition, or a non-function top-level declaration | `UNSUPPORTED_SOURCE` / `INVALID_SOURCE` | the offending node |
| Syntax error under `-std=c11 -pedantic-errors` | `INVALID_SOURCE` | first compiler error |
| Input that parses but fails object compilation | `INVALID_SOURCE` | first `input.c:line:column` in the compiler output |
| Missing compiler or missing libclang | `DEPENDENCY_UNAVAILABLE` | – |
| Analysis or compilation beyond the stage budget | `ANALYSIS_TIMEOUT` | – |

Two details matter for the rest of the team:

- Macro detection does not depend on searching for `#`. The name table is
  checked on raw identifier tokens, so `int f(void){return __LINE__;}` is
  rejected with a location even though the text contains no directive.
- A name is only treated as an extension when libclang lexes it as a keyword.
  `int typeof = 1;` is legal C11 and stays accepted, while `typeof(1) x;` is
  rejected by the reference check.

Macro names inside comments and string literals are ordinary text: they are
lexed as `COMMENT` and `STRING_LITERAL`, so `"__LINE__"` and
`/* __FILE__ */` are accepted. Escaped spellings such as `"a\tb"` keep their
raw text. Token widths are measured in grid cells.

## Character and line rules

- `original_source` is retained byte for byte. `normalized_source` replaces CRLF
  and lone CR with LF; token positions stay on the original line and column.
- A virtual final LF is added for parsing and object compilation when the input
  does not end with a newline. Nothing is added to the returned model.
- Comments are lexed first, then treated as whitespace by the caller. A
  comment's own spelling is preserved with normalized newlines.
- A tab outside tokens is accepted and reported at its original character
  index; a tab inside a token is rejected.

## The `can_join` decision

By default `can_join` re-lexes the complete run plus the candidate and compares
the result with the expected `(kind, spelling)` pairs. The production pipeline
sets `checked_run=True` because Clang has already classified the input tokens
and layout builds the run one checked join at a time. In that case the lexer
starts at the last standalone delimiter (`()[]{},;`) or at the start of the
run if there is none. Keeping the delimiter lets different runs reuse the
same cached suffix. A candidate delimiter can join directly unless it could
complete a trigraph.

- `f` + `(` joins; `a` + `)` joins; `)` + `{` joins.
- `+` + `+`, `/` + `*`, `/` + `/`, `<` + `<`, `-` + `>` do not join: they would
  form one token.
- Three independent `.` tokens are rejected as a run, not pair by pair.
- `1` + `.` and `L` + `"a"` do not join: the concatenation is a different token.
- An empty run is always joinable; an empty spelling is a programming error.

Results are cached in the parent process by expected tokens, compiler flags and
lexer timeout. Cache misses share one serialized child (`LexWorker`) with a
single libclang index, bounded wait and a kill-and-restart path. C still checks
its own context around every join decision; `can_join` itself is a local lexical
helper, not a schedulable stage.

## Process and dependency boundary

A and E share the public process module `codeart.procutil`. A imports
`run_command`, `BuildSession`, `stop_process` and the stop exceptions from it;
`_verification_process` is a compatibility shim and is not imported by any
module in the package. `tests/test_module_boundaries.py` fails if a private
cross-owner import returns, or if `codeart.procutil.__all__` loses a name A uses.

All children start in their own session on POSIX, run under the caller's
`RunContext`, and are killed and reaped by the caller on cancellation or
timeout. The lexer child never outlives the parent: `LexWorker` registers an
`atexit` close and reaps a hung worker before starting the next one.

## Budget and cancellation

`analyze_source` builds an internal context whose deadline is the smaller of the
caller's deadline and `profile.lex_timeout`, so lexing and the object build
share one analysis budget. A cancelled pipeline raises `StageError(CANCELLED)`;
an expired deadline raises `StageError(PIPELINE_TIMEOUT)`; an exhausted analysis
budget raises `ANALYSIS_TIMEOUT`. The diagnostics keep the code and stage, so F
can display them without parsing text.

## Tests and evidence

```sh
python -m pytest -q tests/test_source.py tests/test_source_lexer.py \
  tests/test_source_boundaries.py tests/test_module_boundaries.py
python -m scripts.check_source_diagnostics --output docs/reports/a_source/A_diagnostics.json
```

`tests/test_source.py` keeps the shared-contract, pipeline and cancellation
cases; `tests/test_source_lexer.py` covers worker reuse and restart;
`tests/test_source_boundaries.py` covers input limits, macro and extension
handling, CRLF positions, compiler-error locations and every `can_join`
boundary; `tests/test_module_boundaries.py` guards the A/E import boundary.
`scripts/check_source_diagnostics.py` writes the ten documented demonstration
cases with their codes and positions, and exits nonzero if one changes.
See [the Part A completion checks](../reports/A_source.md) for the recorded run.

## Known limits

- The predefined-macro table is a fixed list. A macro that is neither in the
  table nor expanded as a visible instantiation would surface as an undeclared
  reference instead; the code is still `UNSUPPORTED_SOURCE`, the message differs.
- Extension rejection is keyword-based. An extension that this compiler lexes as
  an ordinary identifier (for example `typeof` written by itself) is caught by
  the reference check rather than by the keyword rule.
- `can_join` decides lexical safety only. It does not prove that the resulting
  layout keeps comments, holes or required separators intact; E's re-lex of the
  complete output remains the final check.
- A tab outside tokens is preserved as a character but the layout stage never
  emits tabs; the generated source uses spaces only.
