# Joern CPG consumer

This directory contains the in-progress Joern consumer for the shared
`external-normalize` scenario. [`versions.json`](versions.json) pins Joern
**4.0.592**, its bundled Java source frontend, and Temurin **21.0.8+9-LTS**.
Type recovery is enabled, name/type fallback is disabled, and Delombok is
disabled. There is no retained result yet: issue #1 has not supplied
the shared application, opaque binary, labels, generated CSMI pack, or evidence
contract.

## Exact identity boundary

`adapter.py` does not derive a Joern method name from a CSMI display name,
descriptor spelling, source text, or regular expression. A callable must carry
exactly one external identity with scheme `io.joern.method-full-name`, version
`4.0.592`, and the adapter must find exactly one external CPG `METHOD` with that
full name. Artifact PURL and comparable digest evidence are checked separately.
Missing, ambiguous, internal, or mismatched evidence fails closed.

Only complete, unprojected CSMI 0.1 core procedure summaries are supported. The
translation uses Joern's documented `argumentIndex` convention:

| CSMI boundary | Joern FlowSemantic slot |
| --- | --- |
| receiver | `0` |
| parameter `n` | `n + 1` |
| normal result `0` | `-1` |

Thus receiver, argument, return, and self-flow mappings remain distinct. A
complete empty transfer set becomes an exact empty `FlowSemantic`, suppressing
Joern's conservative external-call default only where CSMI completeness makes
the negative inference valid. Partial/unknown coverage is never projected.

The production identity-scheme registry is intentionally empty until issue #1
chooses and ships its exact Java scheme. The unit tests inject a test-only
scheme to exercise the adapter; that does not make the example scheme supported
for retained evidence.

## Intended run

Once issue #1 lands its assets:

```sh
consumers/joern/run.sh \
  scenarios/external-normalize \
  /path/to/joern-cli \
  /path/to/temurin-21.0.8 \
  EXPECTED_CSMI_PACK_SHA256 \
  build/joern
```

The Java frontend receives the application root and the opaque JAR only through
`--inference-jar-paths`; the auditable dependency source is never indexed. The
script constructs one CPG, exports exact method evidence, projects the verified
pack, and imports the same CPG for pack-off and pack-on runs. The query differs
only in whether the CSMI-derived semantics are added to `DefaultSemantics`.

`semantics.json` is generated run output and is not a maintained semantic source
of truth. Do not commit it or any analyzer result. Shared labels and final result
validation remain owned by issue #1 and must be consumed in place when present.
