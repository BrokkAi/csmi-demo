# FlowDroid consumer groundwork

This directory contains the strict CSMI-to-FlowDroid adapter groundwork for
[issue #5](https://github.com/BrokkAi/csmi-demo/issues/5). It does **not** yet
contain a runnable interoperability scenario or retained pack-off/on evidence:
[issue #1](https://github.com/BrokkAi/csmi-demo/issues/1) has not produced the
shared binary, generated CSMI pack, labels, manifests, or hashes.

This groundwork validates the supported semantic slice after parsing JSON. A
final consumer must additionally validate issue #1's exact document bytes
against the pinned normative CSMI JSON Schema before invoking the adapter; that
schema/pack integration cannot be fixed until the shared assets and their
identities exist.

The adapter supports only the CSMI 0.1 meaning needed by that scenario:
unprojected `input parameter[n] -> output result[0]` may-information transfers,
and a complete empty `procedure-summaries` set. It matches the exact artifact
PURL, digest coverage, and SHA-256, the configured symbol
scheme/version/stability and ordered descriptors, the callable shape, and
exactly one configured Soot class plus method subsignature. Artifact
mismatches, ambiguity, incomplete coverage,
unsupported projections or roots, and required vocabularies fail closed.

Positive transfers become FlowDroid `MethodFlow` values in an in-memory
`MemorySummaryProvider`. A complete empty set becomes FlowDroid's exact-method
exclusion, and a narrow wrapper makes that excluded method selectable without
marking its whole class complete. This prevents unknown-summary fallback from
inventing a transfer while leaving unrelated methods unsupported.
This exclusion closes only CSMI core procedure transfers; it is not a claim
about effects, exceptions, allocation, mutation, or purity.

No generated FlowDroid XML is checked in. Any future generated summary material
must be disposable output derived from and traceable to the exact CSMI document
digest. The adapter retains that digest and artifact identity separately from
FlowDroid's summary objects, so those objects never become a second semantic
source of truth.

## Pinned environment and dependencies

- Eclipse Temurin JDK `17.0.16+8`
- Apache Maven `3.9.11`
- FlowDroid `2.15.1`, upstream tag commit
  `4d8702611abf64b12a6c7c5e662c201add748bd9`
- Soot `4.7.1`, resolved transitively by FlowDroid
- FlowDroid is an external Maven dependency under LGPL-2.1. No FlowDroid or
  Soot implementation source is copied or vendored into this Apache-2.0 repository.

The Maven enforcer rejects other JDK and Maven versions. From this directory:

```sh
JAVA_HOME=/Users/dave/.sdkman/candidates/java/17.0.16-tem \
PATH=/Users/dave/.sdkman/candidates/java/17.0.16-tem/bin:$PATH \
mvn verify
```

The current tests establish the pinned summary surface's expressiveness and
the adapter's fail-closed behavior only. They are not substitute scenario
fixtures, interoperability evidence, or a precision/recall result.
