# CodeQL consumer

This directory contains a fail-closed CSMI-to-CodeQL adapter, a pinned CodeQL
query, and retained pack-off and pack-on results for the shared
`external-normalize` scenario. It consumes the shared pack, labels, opaque JAR,
and scenario verifier in place; it does not copy their semantics into a second
consumer-owned fixture.

## Reproduce the evidence

Install CodeQL CLI `2.26.4`, use `javac 21.0.8`, then run:

```sh
./consumers/codeql/scripts/run-shared-scenario.sh
python3 consumers/codeql/scripts/verify-results.py
```

The runner verifies the shared scenario, runs the adapter unit tests, resolves
the locked `codeql/java-all` `9.2.3` pack (build SHA
`44a68d3a47fcbcd6a6a76ec7d1c1b3a1a28b201e`), and builds one database rooted
at `analyzer-input`. Its source archive must contain only
`ScenarioApplication.java`; `audit-source` and `producer` are rejected.

Both runs use that same database and [`ExternalNormalize.ql`](query/ExternalNormalize.ql).
The pack-on command differs only by enabling the disposable generated model
pack with `--additional-packs` and `--model-packs`. Results are validated
against the shared labels and written to [`results/`](results/).

## Retained result

Pack-off reports the negative near miss as a true negative and misses the real
normalization flow: one TN and one FN. Precision is undefined because no flow
is reported; recall is `0/1`.

Pack-on reports only `normalize.input-to-return`: one TN and one TP, precision
`1/1`, and recall `1/1`. The evidence therefore establishes a recall change
from `0/1` to `1/1` while preserving the near miss. It does not claim that
precision improved, because pack-off precision is undefined.

## Capability and exactness boundary

The generated model uses CodeQL's `summaryModel` for the CSMI
`parameter[0] -> result[0]` may-information edge and `neutralModel` for the
callable-scoped complete empty transfer set. A CodeQL taint step does not claim
value preservation. A neutral model is not a sanitizer and does not claim
purity or absence of effects.

Java `neutralModel` has no `subtypes` column and CodeQL applies subtype
matching. This adapter therefore accepts the empty summary only for this
scenario's structurally identified receiver-free callable. It rejects an
instance callable rather than widening an exact CSMI absence statement to
overrides. The retained result is a narrow interoperability proof, not a claim
of general CSMI-to-CodeQL completeness.

## Disposable generation

[`generate_model.py`](generate_model.py) validates the shared pack manifest,
Bifrost assembler and producer provenance, resource size and digest, exact JAR
PURL/digest selector, portable JVM identity, receiver-free signatures,
transfers, completeness, and provenance links. It then emits a disposable
CodeQL model pack and `trace.json` outside the repository. Unsupported or
incomplete input fails closed; generated CodeQL rows are never committed as a
second semantic source of truth.
