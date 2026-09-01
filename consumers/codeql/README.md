# CodeQL consumer (adapter groundwork)

This directory contains the fail-closed adapter for issue #3. It does **not**
yet contain a retained CodeQL interoperability result: the shared issue #1
fixture, labels, binary, and producer-generated CSMI pack are not on `main`.

## Capability gate

The pinned surface is CodeQL CLI `2.26.4` with `codeql/java-all` `9.2.3`
(pack build SHA `44a68d3a47fcbcd6a6a76ec7d1c1b3a1a28b201e`). Java model packs expose:

- `summaryModel(..., input, output, kind, provenance)`, which can conservatively
  map the CSMI `parameter[0] -> result[0]` may-information edge to a CodeQL
  `Argument[0] -> ReturnValue` taint step; and
- `neutralModel(package, type, name, signature, "summary", "manual")`, which
  can suppress CodeQL-generated summaries for a complete empty transfer set.

This is deliberately narrower than general CSMI support. A CodeQL taint step
does not claim value preservation. A neutral summary is not a sanitizer and
does not claim purity or absence of effects.

There is also an exactness limitation: Java `neutralModel` has no `subtypes`
column and CodeQL interprets it with subtype matching. The adapter therefore
accepts the negative `constant` model only for the scenario's receiver-free JVM
callable. It rejects an instance callable rather than applying a CSMI exact-
callable absence claim to overrides.

## Disposable generation

Once issue #1 lands, generate the model pack outside the source tree:

```sh
python3 consumers/codeql/generate_model.py \
  --pack scenarios/external-normalize/pack \
  --artifact scenarios/external-normalize/artifacts/external-normalize.jar \
  --output "$RUNNER_TEMP/codeql-csmi-model"
```

Generation validates the manifest resource size and digest, matches the exact
versioned PURL and whole-artifact SHA-256, requires the JVM identity profile
`ai.brokk.csmi.jvm-symbol` `0.1`, checks the exact callable signatures and
complete transfer scopes, and emits `trace.json`. Any mismatch, unsupported
semantic shape, or generation failure exits nonzero. Generated CodeQL data is
disposable and must not be committed as another semantic source of truth.

The query, pack-off/on runner, evidence validator, and CI workflow remain
blocked on the exact shared application, labels, paths, binary, and pack from
issue #1. They must build one database from application inputs that exclude the
external implementation, then run the same query with only this generated
model pack toggled.

