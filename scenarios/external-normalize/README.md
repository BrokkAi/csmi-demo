# External normalize scenario (planned)

This planned scenario exercises two procedures at an external binary boundary.
The application will obtain input values, pass them to opaque Java `normalize`
and `constant` operations, and use the returned values in sinks. `normalize`
preserves its input; `constant` returns a value unrelated to its input. The
intended demonstration is that a consumer can distinguish these cases from a
semantic model even though both implementations are unavailable to the
application analyzer.

## Opaque fixture boundary

The future fixture will be a controlled Java binary artifact containing the
external `normalize` and `constant` operations. Its source, retained for audit
and fixture reproducibility, is **not part of the analyzer-indexed application
inputs**. The application analyzer must see only the opaque binary boundary; it
must not index, inspect, or infer behavior from the auditable source. The
eventual fixture manifest should record the binary identity and source/audit
identity separately, with hashes and build details, so a reviewer can reproduce
the fixture without accidentally giving the analyzer source access.

This README is only a plan. It does not add the Java binary, auditable source,
build output, SDK, semantic pack, analyzer implementation, or CodeQL placeholder.

## Planned flow labels

The eventual scenario should use stable labels such as these and keep them
unchanged across pack-off and pack-on runs:

| Label | Expected flow | Type |
| --- | --- | --- |
| `normalize.input-to-return` | application input → `normalize` normal return → sink | positive |
| `constant.input-to-return` | application input does not flow through `constant` to its normal return or sink | negative |

The table defines the expected behavior, not an analyzer query. The final
scenario artifact should add exact source locations or stable IDs once the
application fixture is designed.

## Planned pack-off / pack-on evidence

The CSMI pack will declare the parameter-to-normal-return transfer for
`normalize`. It will declare complete transfer coverage for `constant` without
such a transfer, making absence meaningful rather than merely unknown.

Run the same application and opaque binary twice:

1. **Pack off:** no CSMI semantic model is available for either operation.
2. **Pack on:** the planned CSMI model for the exact binary is available.

Record each label's expected status and observed status for each run. For the
positive flow, a reported flow is TP and an absent flow is FN. For the negative
case, a report is FP and no report is TN. Any report that cannot be tied to a
stable label, and any incomplete/unsupported run, must be retained as
unresolved evidence rather than silently counted as TN.

The pack-on result must match both labels. The pack-off result must contain at
least one false positive or false negative; otherwise this scenario does not
demonstrate a useful semantic-pack delta for that consumer.

For a run, compute precision as `TP / (TP + FP)` only if `TP + FP > 0`, and
recall as `TP / (TP + FN)` only if `TP + FN > 0`. When a denominator is zero,
write `undefined`/`not applicable` and the denominator. Do not substitute zero
or one. Per-flow records, fixture identity, analyzer/consumer identity, and
pack identity are the primary evidence; precision and recall are derived
summaries.

The scenario remains scaffolding/planned until the opaque fixture, independent
consumer, model, and reproducible evidence workflow are implemented and
reviewed.
