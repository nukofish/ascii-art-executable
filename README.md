# ascii-art-executable
A simple cli tool to reformat C/C++ code into executable ascii art.

## F integration smoke demo

Run from the repository root with Python 3.10 or later. The smoke demo uses
the standard library and the existing Part B mask generator.

For source analysis and the real pipeline, install the pinned Python
dependencies and a C11 Clang compiler. The Python libclang package includes
its native library. Development and regression checks also require pytest.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m codeart.cli --source example.c --shape cat --output generated.c
```

[Source analysis and supported inputs](docs/modules/source.md) describes the
raw lexer, error handling and isolation.

```sh
python3 -m codeart.cli --demo --shape circle --output /tmp/codeart-demo.c
python3 -m pytest -q
```

The CLI supports `circle`, `cat` and `code`. In demo mode a fixed function
is placed into the real mask by smoke-test stubs for A/C/D/E. All four checks
are reported as `NOT_RUN (DEMO_ONLY)`. The file exercises export and LF
preservation. It is a smoke fixture for integration, with production layout,
comment filling and verification supplied by the corresponding modules.

## Integration interface

[Module contracts and handoff rules](docs/modules/contracts.md)

Import request and result types from `codeart.contracts` and call
`codeart.pipeline.generate(request, deps=..., cancel_event=...)`. Omitting
`deps` assembles `source`, `shapes`, `layout`, `fill` and `verify`. A checkout
missing one of these modules reports `DEPENDENCY_UNAVAILABLE`. Existing B
shape types are re-exported from the contract to keep one class per type.

- C gets the mask builder and join checker as keyword arguments. Pass the same
  context to B and keep attempt history on the layout plan.
- For A–E, call `ctx.check()` during work. For any external process, use the
  smaller of its stage budget and `ctx.remaining_s()` and terminate the child
  on cancellation or timeout. Use `StageError(Diagnostic(...))` for a diagnosed
  stage failure. The pipeline preserves a plan or output once the stage returns.
- Positions in placements and the render map use zero-based grid coordinates.
  User-facing diagnostic and token locations use one-based source coordinates.
- The production caller supplies the compiler/lexer profile shared by A and E.
  Ordinary input passes `fixtures=None`. A built-in sample must pass the
  selection object from E along with its matching source.
- E uses the shared verification types. Its lexer callback receives a context
  with the shared budget API and a deadline capped by the lexer stage.

The local web interface, production profile and pinned font remain integration
milestones after the CLI smoke test.
