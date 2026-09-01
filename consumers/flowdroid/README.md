# FlowDroid consumer

This directory contains the pinned CSMI-to-FlowDroid adapter and the runnable
pack-off half of the shared `external-normalize` scenario from
[issue #5](https://github.com/BrokkAi/csmi-demo/issues/5). The pack-on half is
still blocked: the shared scenario records no generated CSMI pack because
[Bifrost issue #2841](https://github.com/BrokkAi/bifrost-dev/issues/2841)
prevents export of its complete empty `constant` summary. No hand-authored pack
or substitute transfer is used here.

## Pinned environment and dependencies

- Eclipse Temurin JDK `17.0.16+8`
- Apache Maven `3.9.11`, downloaded by the script-only Maven wrapper with a
  pinned distribution SHA-256
- FlowDroid `2.15.1`, upstream tag commit
  `4d8702611abf64b12a6c7c5e662c201add748bd9`
- Soot `4.7.1`, resolved transitively by FlowDroid

The Maven enforcer rejects other JDK and Maven versions. FlowDroid remains an
external LGPL-2.1 Maven dependency; no FlowDroid or Soot implementation source
is copied into this Apache-2.0 repository.

## Pack-off run

From this directory, with the pinned JDK selected:

```sh
./mvnw --batch-mode --no-transfer-progress verify
./mvnw --batch-mode --no-transfer-progress -q compile exec:java \
  -Dexec.mainClass=ai.brokk.csmi.flowdroid.FlowDroidPackOffCli \
  -Dexec.args="--scenario ../../scenarios/external-normalize --output results/pack-off.json --pack off --consumer-revision $(git rev-parse HEAD)"
```

The CLI reads the scenario and shared labels in place. Before analysis it
verifies the manifest-recorded SHA-256 values for the opaque JAR, analyzer
application source, and labels. It compiles only the exact analyzer application
source with only the opaque JAR on the compiler classpath. The audit source is
never traversed or compiled.

FlowDroid receives the compiled application as its application path and the
opaque JAR as its library path. It uses CHA, one analysis thread, bounded
timeouts, exact source/sink and entry-point signatures, and excludes only
`ai.brokk.csmi.demo.ExternalNormalizer` with no bodies for excluded code. Source
and sink definitions stay consumer-local and are not treated as CSMI facts.

The retained local result is [`evidence/pack-off.json`](evidence/pack-off.json).
It records the exact consumer revision, scenario, fixture, dependency,
environment, configuration, termination, and per-label identities. The
complete pack-off result is:

| Label | Expected | Observed | Classification |
| --- | ---: | ---: | --- |
| `constant.input-to-return` | false | false | TN |
| `normalize.input-to-return` | true | false | FN |

Counts are TP 0, TN 1, FP 0, FN 1. Precision is undefined because its
denominator is zero; recall is `0/1 = 0`. This establishes the required
pack-off difference without claiming any pack-on result.

## Adapter boundary and remaining blocker

The adapter supports only the CSMI 0.1 slice required by this scenario:
unprojected `input parameter[n] -> output result[0]` may-information transfers,
and a complete empty `procedure-summaries` set. It matches the exact artifact
PURL, digest coverage and SHA-256, symbol scheme/version/stability and ordered
descriptors, callable shape, and exactly one configured Soot class plus method
subsignature. Artifact mismatch, ambiguity, incomplete coverage, unsupported
roots or projections, and required vocabularies fail closed.

Positive transfers become FlowDroid `MethodFlow` values in an in-memory
`MemorySummaryProvider`. A complete empty set becomes an exact-method exclusion;
the wrapper does not mark the whole class complete. Generated FlowDroid summary
material is therefore disposable and remains traceable to the input CSMI digest
rather than becoming a second semantic source of truth.

The adapter tests prove that this pinned API can represent both meanings and
cover identity, index mapping, artifact mismatch, ambiguity, unsupported
semantics, and incomplete evidence. They are not pack-on evidence. Once the
Bifrost-generated pack exists, the remaining work is to validate its exact
bytes against the pinned normative schema, invoke this adapter, rerun the same
analysis with only its summary provider enabled, retain pack-on evidence, and
compare the two results. Until then the CLI rejects `--pack on`, CI runs only
the honest pack-off scenario, and issue #5's full acceptance criteria remain
blocked.
