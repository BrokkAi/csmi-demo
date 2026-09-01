# FlowDroid consumer

This directory contains a strict CSMI v0.1 adapter for FlowDroid `2.15.1` and
Soot `4.7.1`, plus retained pack-off/on results for the shared
`external-normalize` scenario from issue #5. FlowDroid and Soot remain external
LGPL-2.1 Maven dependencies; no implementation source is copied into this
Apache-2.0 repository.

## Pinned environment

- Eclipse Temurin JDK `17.0.16+8`
- Apache Maven `3.9.11`, via the script-only wrapper and pinned distribution
  SHA-256
- FlowDroid `2.15.1`, upstream tag commit
  `4d8702611abf64b12a6c7c5e662c201add748bd9`
- Soot `4.7.1`, resolved transitively

The Maven enforcer rejects other Java and Maven versions. From this directory:

```sh
./mvnw --batch-mode --no-transfer-progress verify
./scripts/run-shared-scenario.sh
```

The scenario script runs identical FlowDroid inputs and configuration twice.
The opaque JAR remains on the library path, its implementation source remains
outside the analyzer input, and `ExternalNormalizer` is excluded with no active
bodies. Only the CSMI-derived `SummaryTaintWrapper` changes between pack off and
pack on. Shared scenario assets, labels, and pack bytes are read in place rather
than copied into this consumer.

## Exact CSMI boundary

Before pack-on analysis, the consumer validates the scenario, pack manifest,
resource size and SHA-256, media type, artifact PURL and exact JAR digest. It
maps the landed `ai.brokk.csmi.jvm-symbol` structural identities to exactly:

- `java.lang.String constant(java.lang.String)`
- `java.lang.String normalize(java.lang.String)`

The adapter supports only complete, unprojected parameter-to-normal-result
may-information transfers required by this scenario. `normalize` becomes one
FlowDroid parameter-to-return `MethodFlow`; the complete empty `constant`
summary becomes FlowDroid's exact-method exclusion. The exclusion does not mark
the class complete. Artifact mismatch, ambiguous structural binding,
incomplete evidence, projections, unsupported required vocabularies,
compatibility constraints, consumer-resolved dependencies, and unresolved
provenance fail closed.

Generated FlowDroid summary objects are disposable runtime material. The
retained pack-on result records the exact CSMI manifest digest, semantic
document digest, producer identity, input artifact identity, and provenance
record used to create them; those objects never become another semantic source
of truth.

## Retained evidence

[`results/pack-off.json`](results/pack-off.json) and
[`results/pack-on.json`](results/pack-on.json) implement the repository
`csmi-demo-consumer-result/1` contract. They retain exact tool, operating-system,
scenario, analyzer-configuration, artifact, pack, and provenance identities.
The per-flow result is:

| Label | Pack off | Pack on |
| --- | --- | --- |
| `constant.input-to-return` | TN | TN |
| `normalize.input-to-return` | FN | TP |

Pack off has TP 0, TN 1, FP 0, FN 1. Its precision is undefined because the
denominator is zero, and recall is `0/1`. Pack on has TP 1, TN 1, FP 0, FN 0,
with precision and recall both `1/1`. The negative near miss remains negative;
the exact CSMI transfer recovers only the positive flow.

Focused tests cover exact method identity and parameter/result mapping,
complete-empty exclusion, artifact mismatch, ambiguous binding, structural
near misses, incomplete coverage, projections, invalid indices, required
vocabularies, changed pack bytes, analyzer-source isolation, strict label
extraction, provenance, and the real pack-off/on transition. The shared
scenario verifier independently validates its deterministic fixture, pack,
producer, boundary, and hashes.
