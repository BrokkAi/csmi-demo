# Minimal dataflow consumer

This directory contains an intentionally small, independent CSMI v0.1
consumer. It is an experiment-specific graph reachability analyzer, not a CSMI
SDK. It has no Bifrost dependency and does not read source code, class files, or
any producer-internal representation.

The consumer reads an analyzer input containing nodes, ordinary dataflow edges,
and external calls whose targets are expressed as full CSMI structural symbol
identities. With the pack off, external calls contribute no input-to-output
edges. With the pack on, the consumer adds only transfers justified by an
applicable, integrity-checked, complete CSMI procedure summary. It then computes
source-to-sink reachability. Expected labels are loaded only afterward and are
used solely to score the already-computed result.

[`inputs/external-normalize.json`](inputs/external-normalize.json) is the
consumer-local query and analyzer graph for the shared fixture. It records call
relationships using exact JVM structural identities and the shared binary
artifact selector. It does not contain library implementation semantics or
expected outcomes. Those identities are validated against the shared scenario
manifest and, when available, the generated CSMI pack.

## Version and requirements

- consumer: `brokkai.csmi.minimal-dataflow` version `0.1.0`
- Python: 3.9 or newer (validated with CPython 3.9.6)
- CSMI semantic model: exactly `0.1`
- CSMI JSON serialization: exactly `0.1-json`
- CSMI pack format: exactly `0.1`
- third-party dependencies: none

The normative CSMI schema and specification are maintained in the
[`code-semantic-model-interchange`](https://github.com/BrokkAi/code-semantic-model-interchange)
repository. This consumer intentionally implements only the artifact selector,
structural symbol, callable declaration, parameter-to-result transfer,
procedure-summary completeness, and provenance semantics needed by the shared
scenario.

## Commands

From this directory:

```bash
python3 -m unittest discover -s tests -v
./scripts/run-shared-scenario.sh
```

The shared deterministic fixture and labels landed in repository commit
`52202836636ccd7b5417134b25af3adfbb3f1118`. The command validates their pinned
digests and analyzer boundary in place; it never copies the shared binary,
labels, producer input, or future pack into this consumer.

The retained [`pack-off.json`](results/pack-off.json) is a completed consumer
run against those shared identities. [`pack-on.json`](results/pack-on.json) is
deliberately a typed `pack-unavailable` failure, not interoperability evidence:
the shared scenario currently records Bifrost issue
[`#2841`](https://github.com/BrokkAi/bifrost-dev/issues/2841), diagnostic
`summary.empty`, and no generated CSMI pack identity. Once issue #1 replaces
that blocker with an available manifest and digest, the same script will invoke
the pack-on analysis; its expected-exit check must then be updated together with
a retained successful result.

The unit tests use temporary diagnostic documents to validate consumer
semantics. Those documents are deliberately not committed as substitute CSMI
packs or interoperability results.

The output is always machine-readable JSON. Successful results contain exact
consumer, scenario, artifact, and pack identities; per-flow expected and
observed outcomes; TP/FP/FN/TN counts; and denominator-aware precision and
recall. The analyzer graph is identified by its canonical JSON SHA-256.
Failures retain the identities established before the failure, contain a stable
`failure.code` and details, and exit with status 2. Undefined metrics are
encoded as `{ "defined": false, "denominator": 0 }`.

## Fail-closed boundary and limitations

The pack-on run rejects malformed or non-canonical JSON, integrity failures,
artifact mismatch or indeterminacy, duplicate or unresolved structural symbol
identity, unsupported required vocabularies or projections, consumer-resolved
declaration dependencies, missing provenance, and non-complete summary
coverage. These conditions are not converted into an empty model or a clean
analysis.

The consumer accepts only exact-version PURLs and exact SHA-256 artifact
digests. It does not implement VERS, compatibility vocabularies, projections,
receivers, output parameters, exceptions, captures, or pack combination.
Encountering required semantics outside the supported parameter-to-result core
is an explicit `unsupported-semantics` result.

For this scenario, the standardized fact that changes analysis is a complete
core `procedureSummaries` claim: `input parameter[0]` transfers to `output
result[0]` for the positive callable, while complete coverage with an empty
transfer set makes the negative near miss an established non-flow. The consumer
does not infer either outcome from callable names or expected labels.

The currently retained pack-off run has one false negative and one true
negative. Precision is undefined because it reports no positive flows; recall
is `0/1`. No pack-on precision, recall, or interoperability claim is made while
the shared generated pack is unavailable.
