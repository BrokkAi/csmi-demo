# Shared scenarios

This directory is the analyzer-neutral scenario contract for the demo. A
scenario describes the application-side code, the external boundary, the
expected per-flow labels, and the evidence to collect. It does not prescribe an
analyzer implementation, SDK, query language, generated artifact, or pack
format.

Consumers under [`../consumers/`](../consumers/) should use the same scenarios
for pack-off and pack-on runs. Keeping scenarios shared prevents each consumer
from quietly changing the ground truth or measuring a different fixture.

## Scenario contents

Each scenario directory should document:

- the application code and its source-of-truth expected behavior;
- the external boundary and what is intentionally unavailable to the analyzer;
- stable identifiers for every positive and negative flow;
- the pack-off and pack-on setup, including exact artifact/configuration
  identity when those become available; and
- the result schema and rules for incomplete, unsupported, or failed runs.

Expected labels are per flow. A summary should preserve true positives (TP),
false positives (FP), false negatives (FN), and true negatives (TN), rather
than collapsing a run to “worked” or “did not work.” Precision is `TP / (TP +
FP)` only where `TP + FP > 0`; recall is `TP / (TP + FN)` only where `TP + FN >
0`. A zero denominator makes that metric undefined/not applicable, not zero and
not one.

[`external-normalize`](external-normalize/) materializes the first deterministic
opaque fixture, shared labels, and exact Bifrost-generated CSMI pack. This is
not published benchmark evidence and does not claim that a consumer result
exists.

[`node-builtin-alias`](node-builtin-alias/) is a profile-identity scenario. It
pins an exact official Node distribution and tests builtin alias equality plus
a same-spelled npm-package near miss; it does not claim procedure semantics.
