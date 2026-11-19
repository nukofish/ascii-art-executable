# Acceptance evidence

Each report names its tested commit and indicates uncommitted changes.
Use the columns Commit, Input, Command, Expected, Actual, Evidence and Status.
Keep PASS, FAIL and NOT_RUN distinct.

Store fixed-height evidence under `fixed/` and growth demonstrations under
`scaled/`. Name source files
`case_<function>_<shape>_h<rows>_s<scale>.c` and pair them with JSON reports.
Do not overwrite an earlier run when the source or revision differs.

## Report index

- [Current status and reproduction commands](../../README.md#status)
- [Part A source and lexical checks](A_source.md)
- [Part B shape checks](B_shapes.md)
- [Part C layout checks](C_layout.md)
- [Part D completion checklist](D_checklist.md)
- [Part D detailed report](D_report.md)
- [Part E verification completion checklist](E_verify.md)
  and [v1.5 budget and coverage decision](E_verify.md#v15-budget-and-coverage-decision)
- [Whole-program acceptance samples](whole_program/README.md)
  and [whole-program budgets and coverage](E_verify.md#whole-program-budgets-and-coverage)
- [Part F original checks](F_acceptance.md)
- [Part F after E integration](F_after_E.md)
- [Part F CI and bilingual documentation follow-up](F_delivery.md)
- [Part F complete-file entry and code-fill indicator](F_prepass.md)

Functional acceptance and owner completion sheets have separate version
anchors. A functional PASS does not imply every owner has submitted a
second-round completion sheet. Each owner adds their own sheet to this index.

## Handoffs

- A owns input limits, lexical boundaries and diagnostic locations, and guards the
  shared process boundary in `codeart.procutil`. The sheet is
  [A_source.md](A_source.md), with evidence under [`a_source/`](a_source/).
- B supplies geometry reference JSON and assertion definitions. E's acceptance
  command loads the h32, h64 and h128 fixtures for scales 1, 2 and 4. B keeps
  h96 as a scale-3 regression fixture. The B checklist, the measured numbers
  and the B→E handoff (current-height centroid with the `−0.5` cell-index
  correction, `base_area` from h32) are in
  [B_shapes.md](B_shapes.md), with evidence under
  [`b_shapes/`](b_shapes/). See the
  [verification guide](../modules/verify.md#fixed-size-acceptance) for the report fields.
- C owns the narrow-span hollow CODE and longest-token growth regressions.
- D reports token, block-comment and line-comment contributions separately.
- E distinguishes fixed h32 behavior evidence from grown cases, and records
  `OUTPUT_TOO_LARGE` as NOT_RUN due to size. The current builtin registry
  provides exact fixture identity. Moving builtin sources to separate C
  files is a follow-up for E that must preserve that identity and input set.
- F owns local operation, preview, exports, environment setup and CI.

## Automatic growth demonstration

Run the production CLI with the default initial scale. The input has a
string token that is too wide for the circle at 32 or 40 rows.

```sh
run_dir=$(mktemp -d)
python -m codeart.cli --source docs/reports/scaled/auto_grow_input.c --shape circle \
  --output "$run_dir/case_auto_grow_circle_h50_s1.5625.c" \
  --report "$run_dir/case_auto_grow_circle_h50_s1.5625.json"
```

A clean checkout of `571ce7dffa4356a31f6ecc09f475ea72a42a3064` recorded
failed attempts at 32 and 40 rows, then succeeded at 50 rows. Token, geometry
and compilation passed. Behavior was `NOT_RUN (NO_FIXTURE)` for the custom
input. The [generated C file](scaled/case_auto_grow_circle_h50_s1.5625.c)
and [JSON report](scaled/case_auto_grow_circle_h50_s1.5625.json) preserve the
output and attempt history.

## Error demonstrations

1. Non-ASCII input produces `UNSUPPORTED_SOURCE` with source line and column.
2. A function using `__LINE__` produces `UNSUPPORTED_SOURCE` without requiring
   a preprocessing directive.
3. A token wider than the configured layout can accommodate produces
   `LAYOUT_LIMIT` with `diagnostic.details["attempt_history"]`.

The public `codeart.procutil` module is shared by A and E.
