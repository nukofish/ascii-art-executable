# Source analysis and lexical boundaries

Part A accepts one self-contained C11 function using printable ASCII source.
Parameters, automatic local declarations and recursive calls are supported.
Static local variables, including static const variables, are rejected because
they retain storage across calls. This keeps the supported input scope free
of persistent local state. External
functions and objects, top-level declarations, preprocessing directives,
predefined macros, trigraphs, line splicing and real tabs inside tokens
produce shared diagnostics. Non-ASCII comments are also rejected. Escaped
spellings such as `"a\tb"` are preserved.

Import the public types from `codeart.contracts`. Call
`analyze_source(text, profile, *, ctx)` to obtain a `SourceModel`.
The default `VerificationProfile` uses `-std=c11 -pedantic-errors`.
A binds a raw lexer callback to the returned model's profile when needed.
F forwards that effective profile to E, which compares token kinds and
spellings using the same libclang interface.

Input text is retained in `original_source`. CRLF and lone CR are normalized
to LF in `normalized_source`. A virtual final LF is added for parsing and
object compilation when absent. Token positions remain one-based and raw
token spellings come from original source ranges. Comments are returned
separately as shared `Token` values.

The native parser runs in an isolated Python child using the pinned libclang
package. F's existing process runner terminates and reaps the child or process
group on cancellation or timeout. Parsing and original-source object
compilation share one analysis budget, capped by the pipeline deadline.
The same raw lexer is exposed as `lex_source(text, *, ctx)` for E. Ordinary
input has no behavior fixture and E records `NO_FIXTURE`.

`can_join(run_tokens, next_token, profile)` re-lexes the entire contiguous
token run. It compares both token kind and raw spelling and caches completed
decisions by tokens, compiler flags and lexer timeout. Cache misses share
one serialized child process and reuse its libclang index. Requests have
bounded wait and execution times. A hung or failed child is terminated and
reaped; a subsequent request can start a fresh child. The worker is closed
when the parent exits. C checks its context before and after join decisions
as part of its token loop.

Install the pinned dependencies from `requirements.txt` and make a C11
Clang compiler available on PATH. For tests, install `requirements-dev.txt`
and run `python -m pytest -q`. The source tests include the complete six
function by three shape pipeline matrix and 144 behavior comparisons.

Diagnostic codes and structured locations are the interface for callers and
tests. Human-readable messages can differ between AST and compiler paths.
External calls and undeclared objects both use `UNSUPPORTED_SOURCE`.
