# CodeQL consumer (blocked diagnostic)

This directory contains the fail-closed CodeQL adapter and the runnable
pack-off diagnostic for issue #3. It does **not** contain a retained
interoperability result: the shared fixture and labels are present, but the
Bifrost-produced CSMI pack remains unavailable because
[Bifrost issue #2841](https://github.com/BrokkAi/bifrost-dev/issues/2841) is
open.

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

## Blocked diagnostic

Run the diagnostic with the exact pinned CLI:

```sh
./consumers/codeql/run-blocked-diagnostic.sh /tmp/codeql-blocked.json
```

It verifies the shared fixture, runs the Python tests, resolves the locked query
pack, builds one CodeQL database rooted at `analyzer-input`, proves through the
database source archive that `audit-source` and `producer` were not extracted,
and runs [`ExternalNormalize.ql`](query/ExternalNormalize.ql) with no model
pack. The current diagnostic reports no labels. That observation is explicitly
recorded as `diagnostic-only`: it is not classified as retained false-negative
evidence without the matching pack-on run.

The emitted JSON preserves the exact fixture, query, CLI, library-pack, and
upstream-blocker identities. Pack-on is `blocked`; the paired comparison,
counts, precision, and recall are `null`. If the scenario leaves its typed
blocked state or the database crosses the analyzer boundary, validation fails
closed.

## Disposable generation

When Bifrost can export the shared pack, generate the CodeQL model pack outside
the source tree:

```sh
python3 consumers/codeql/generate_model.py \
  --pack scenarios/external-normalize/pack \
  --artifact scenarios/external-normalize/analyzer-input/lib/external-normalize-1.0.0.jar \
  --output "$RUNNER_TEMP/codeql-csmi-model"
```

Generation validates the manifest resource size and digest, matches the exact
Maven PURL and `jar` SHA-256 selector, requires the JVM identity profile
`ai.brokk.csmi.jvm-symbol` `0.1`, checks the exact static callable signatures and
complete transfer scopes, and emits `trace.json`. Any mismatch, unsupported
semantic shape, or generation failure exits nonzero. Generated CodeQL data is
disposable and must not be committed as another semantic source of truth.

The future paired run must reuse the same database and query with only
`--additional-packs` and
`--model-packs=brokkai/csmi-external-normalize-model@0.0.0` added. Until a valid
Bifrost pack exists, no pack-on result or precision/recall claim is made.
