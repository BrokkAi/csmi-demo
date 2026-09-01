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
python3 -m minimal_dataflow.cli \
  --analysis ../../scenarios/external-normalize/analyzer-input.json \
  --artifact ../../scenarios/external-normalize/artifact.json \
  --labels ../../scenarios/external-normalize/labels.json \
  --pack off \
  --scenario-identity-file ../../scenarios/external-normalize/scenario-identity.json \
  --output results/pack-off.json
python3 -m minimal_dataflow.cli \
  --analysis ../../scenarios/external-normalize/analyzer-input.json \
  --artifact ../../scenarios/external-normalize/artifact.json \
  --labels ../../scenarios/external-normalize/labels.json \
  --pack ../../scenarios/external-normalize/csmi-pack \
  --expected-pack-digest-file ../../scenarios/external-normalize/pack-identity.json \
  --scenario-identity-file ../../scenarios/external-normalize/scenario-identity.json \
  --output results/pack-on.json
```

Those scenario paths are owned by issue #1 and are not present on the original
scaffolding base. Until the generated shared pack and fixtures land, the
commands above describe the integration boundary rather than retained evidence.
The unit tests use temporary diagnostic documents to validate consumer
semantics; those documents are deliberately not committed as substitute CSMI
packs or interoperability results.

The output is always machine-readable JSON. Successful results contain exact
consumer, scenario, artifact, and pack identities; per-flow expected and
observed outcomes; TP/FP/FN/TN counts; and denominator-aware precision and
recall. Failures contain a stable `failure.code` and details and exit with status
2. Undefined metrics are encoded as `{ "defined": false, "denominator": 0 }`.

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
