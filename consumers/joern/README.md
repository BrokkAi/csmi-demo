# Joern CPG consumer

This directory contains the Joern consumer groundwork for the shared
`external-normalize` scenario. [`versions.json`](versions.json) pins Joern
**4.0.592**, its bundled Java source frontend, and Temurin **21.0.8+9-LTS**.
Type recovery is enabled, name/type fallback is disabled, and Delombok is
disabled. The shared application, opaque binary, labels, CSMI pack, and evidence
contract are consumed in place from `scenarios/external-normalize`.

## Exact identity boundary

`adapter.py` supports the landed `ai.brokk.csmi.jvm-symbol` 0.1 profile. It
constructs the owner, callable name, parameter types, and result type from the
portable descriptor paths and declaration/type references, then requires
exactly one external Joern `METHOD` whose resolver-produced `name`, `signature`,
and `fullName` equal that structural identity. It never uses a display name,
source text, regular expression, or fuzzy lookup. Artifact PURL and comparable
digest evidence are checked separately, including the bytes of the JAR passed to
Joern. Missing, ambiguous, internal, or mismatched evidence fails closed.

Only complete, unprojected CSMI 0.1 core procedure summaries are supported. The
translation uses Joern's documented `argumentIndex` convention:

| CSMI boundary | Joern FlowSemantic slot |
| --- | --- |
| receiver | `0` |
| input parameter `n` | `n + 1` |
| normal result `0` | `-1` |

Thus receiver, argument, return, and receiver self-flow mappings remain
distinct. Unprojected output parameters fail closed because this consumer
supports no required caller-visible writeback vocabulary. A complete empty CSMI
transfer set becomes no Joern cross-boundary mappings. Joern 4.0.592 additionally
needs input self-mappings for its synthetic static qualifier and each parameter
so an empty summary does not fall back to argument-to-argument overpropagation.
The adapter records those operational `joernInputSelfMappings` separately from
`csmiTransferMappings`; they preserve inputs but do not assert a CSMI boundary
transfer. Partial/unknown coverage is never projected.

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
CPG for both queries. Only the CSMI-derived custom semantics are toggled. It
validates the shared result contract, requires the pack-on run to match every
label, and requires a real error delta in the pack-off baseline.

The retained [`evidence/pack-off.json`](evidence/pack-off.json) records one true
positive and one false positive (precision 0.5, recall 1.0). The retained
[`evidence/pack-on.json`](evidence/pack-on.json) records one true positive and one
true negative (precision 1.0, recall 1.0). Both results use the repository's
`csmi-demo-consumer-result/1` contract and bind the Joern configuration, shared
manifest and labels, opaque JAR, generated CPG, and method evidence by SHA-256.
The pack-on result additionally binds the exact adapter output and preserves the
pack, semantic-document, and producer provenance identities.

`semantics.json`, the CPG, method inventory, and raw path observations are
generated run outputs, not maintained semantic sources of truth. Do not commit
them. The normalized evidence is validated against the shared labels before it
is retained. Pack-on execution always projects the shared pack through
`adapter.py`; it does not substitute hand-authored Joern semantics.
