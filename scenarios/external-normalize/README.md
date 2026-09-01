# External normalize scenario

This shared Java scenario fixes one opaque binary boundary and two expected
information-flow labels. It contains no consumer query, analyzer result, or
precision/recall claim.

## Boundary

Only [`analyzer-input/`](analyzer-input/) is an analyzer input root. It contains
the application source and the pinned library JAR. The auditable library source
lives separately under [`audit-source/`](audit-source/) and **must never be
added to an analyzer database, source root, extraction command, or index**.

The application calls two static methods with identical JVM shapes:

- `ExternalNormalizer.normalize(String)` returns its argument;
- `ExternalNormalizer.constant(String)` returns a fixed unrelated value.

The machine-readable ground truth is [`labels.json`](labels.json). Source and
sink definitions remain consumer-local query concepts; labels state only the
expected end-to-end flow through each call.

## Reproduce and verify

The fixture is built with Eclipse Temurin JDK `21.0.8+9-LTS`, using `javac
21.0.8` and `jar 21.0.8`. The class-file target is Java 17 (`--release 17`). No
network dependency or separate build tool is involved.

```sh
./scenarios/external-normalize/scripts/build-fixture.sh
./scenarios/external-normalize/scripts/verify.py
```

The build script compiles in a temporary directory, fixes the JAR entry time,
and refuses to overwrite the retained artifact unless the bytes equal the
pinned SHA-256. While export is blocked, the verifier checks source,
application, JAR, labels, producer input, intended transfers and completeness,
the analyzer/audit boundary, and that no unverified CSMI pack is present.

## CSMI production blocker

The deterministic fixture and labels are materialized, but this scenario is
not yet complete. Bifrost commit
`d883a143f31aba973401ad079e313bf080aafe17` (the merge of Bifrost PR #2840)
cannot export the required negative summary from its authored-pack boundary:
the internal compiler rejects a complete empty transfer set with
`summary.empty` before `export_authored_csmi_pack` runs.

The exact attempted producer input is
[`producer/bifrost-model.json`](producer/bifrost-model.json), and the reproduced
capability failure is recorded in [`BLOCKER.md`](BLOCKER.md) and
[`scenario.json`](scenario.json). No CSMI pack is retained: adding a fake
transfer, misusing an unrelated Bifrost semantic solely to bypass the compiler,
or hand-authoring final CSMI bytes would manufacture interoperability evidence.
