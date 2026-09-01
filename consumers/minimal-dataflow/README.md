# Minimal dataflow consumer (planned)

This directory reserves a home for the first independent, analyzer-neutral
consumer. The planned consumer will read the shared scenario contract and
compare the flow labels observed with semantic packs disabled and enabled.

No analyzer code, SDK, generated artifact, semantic pack, or CodeQL model is
included here. The implementation, input adapter, and versioned CSMI dependency
are all still to be designed.

## Planned experiment

The consumer will run the same scenario twice:

1. **Pack off:** analyze the application without the external semantic model.
2. **Pack on:** analyze the same application and fixture with the model made
   available through the future CSMI boundary.

The comparison must use the per-flow labels in the scenario README, not a
single aggregate score. For each expected flow, record whether the run reported
it and whether that report is correct. Keep the fixture, consumer version,
configuration, pack identity (when on), and run status with the result.

## Planned evidence vocabulary

For a given run, classify each labeled flow as:

- **TP:** an expected flow was reported;
- **FN:** an expected flow was not reported;
- **FP:** a flow was reported that is not expected by the scenario; and
- **TN:** a non-flow negative case was correctly left unreported.

Precision is `TP / (TP + FP)` only when `TP + FP > 0`. Recall is
`TP / (TP + FN)` only when `TP + FN > 0`. If either denominator is zero, report
that metric as not applicable/undefined with the denominator, rather than
inventing a zero or a perfect score. Per-flow results and the denominator
counts remain primary evidence; aggregate metrics are only a summary.

Results are planned evidence only until a reproducible implementation and
independent rerun exist. An unavailable, partial, or unsupported run must be
labelled as such and must not be presented as pack success.

When implemented, the consumer will emit separate machine-readable pack-off and
pack-on JSON results. Each result will record the consumer name and exact
version, scenario and CSMI artifact identity, pack state, per-flow expected and
observed outcomes, TP/FP/FN/TN counts, and the denominator-safe derived metrics
defined above. The concrete JSON schema will be added with the implementation,
not invented by this scaffold.
