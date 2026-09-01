# Joern CPG consumer

This directory contains the Joern consumer groundwork for the shared
`external-normalize` scenario. [`versions.json`](versions.json) pins Joern
**4.0.592**, its bundled Java source frontend, and Temurin **21.0.8+9-LTS**.
Type recovery is enabled, name/type fallback is disabled, and Delombok is
disabled. Issue #1 has supplied the shared application, opaque binary, labels,
and evidence contract. The Bifrost-generated CSMI pack is still unavailable for
the exact `summary.empty` blocker recorded in the scenario manifest and
[`BLOCKER.md`](../../scenarios/external-normalize/BLOCKER.md).

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
| input parameter `n` | `n + 1` |
| normal result `0` | `-1` |

Thus receiver, argument, return, and receiver self-flow mappings remain
distinct. Unprojected output parameters fail closed because this consumer
supports no required caller-visible writeback vocabulary. A
complete empty transfer set becomes an exact empty `FlowSemantic`, suppressing
Joern's conservative external-call default only where CSMI completeness makes
the negative inference valid. Partial/unknown coverage is never projected.

The production identity-scheme registry remains intentionally empty until the
generated pack establishes the exact Java symbol scheme and carries Joern's
pinned external method identities. The unit tests inject a test-only scheme to
exercise the adapter; that does not make the example scheme supported for
retained evidence.

## Reproduce the current evidence

Install the pinned CSMI schema validator before a pack-on run:

```sh
python3 -m pip install --requirement consumers/joern/requirements-validation.txt
```

```sh
consumers/joern/run.sh \
  scenarios/external-normalize \
  /path/to/joern-cli \
  /path/to/temurin-21.0.8 \
  build/joern
```

The Java frontend receives the application root and the opaque JAR only through
`--inference-jar-paths`; the auditable dependency source is never indexed. The
script constructs one CPG, exports exact method evidence, and imports the same
CPG for the pack-off query. Today it writes a complete `pack-off.json`, writes
`pack-on.json` with `status: unavailable` and unresolved observations, then
exits 3. This is the expected blocked result; it does not convert unavailable
coverage into true negatives.

The retained [`evidence/pack-off.json`](evidence/pack-off.json) records one true
positive and one false positive (precision 0.5, recall 1.0). The retained
[`evidence/pack-on-unavailable.json`](evidence/pack-on-unavailable.json) records
the exact upstream blocker with null counts and metrics. Both results bind the
Joern configuration, shared manifest and labels, opaque JAR, generated CPG, and
external method evidence by SHA-256.

`semantics.json`, the CPG, method inventory, and raw path observations are
generated run outputs, not maintained semantic sources of truth. Do not commit
them. The normalized evidence is validated against the shared labels before it
is retained. Once the generated pack lands, pack-on execution must project that
pack through `adapter.py`; it must not substitute hand-authored Joern semantics.
