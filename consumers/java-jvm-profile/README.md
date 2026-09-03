# Java/JVM profile consumer

This is a small, dependency-free independent consumer for the exact `0.1`
Java/JVM profile family. It validates and projects all four standard
vocabularies in the fixture:

- `csmi.java-source-identity` — resolver-shaped Java source identity;
- `csmi.jvm-binary-identity` — JVM owner, member name, descriptor, and base
  class-file variant;
- `csmi.java-jvm-mapping` — an exact source-to-binary relation backed by
  verified build evidence; and
- `csmi.jvm-compatibility` — inclusive Java release, class-file major, and
  target-platform constraints.

Source and binary symbols remain separate identities. The mapping is accepted
only when its local handles resolve to those exact schemes and its evidence is
present. Display names, source text, descriptor resemblance, producer-local
IDs, or a constraint value are never used as identity or candidate evidence.

The candidate runtime/class-file/platform is deliberately supplied separately:
constraints describe what is required, not what was observed. Missing candidate
evidence, unsupported required versions, incomplete mapping coverage, and
incompatible constraints fail closed.

Run the consumer and tests from the repository root:

```sh
python3 consumers/java-jvm-profile/verify.py \
  --java-release 17 \
  --class-file-major 61 \
  --target-platform jvm
python3 -m unittest discover -s consumers/java-jvm-profile -p 'test_*.py' -v
```

The fixture is an exact byte-for-byte copy of
[`fixtures/valid/java-jvm-mapping.json`](https://github.com/BrokkAi/code-semantic-model-interchange/blob/6d258a827962542b45b3baf085cd2dfecdda8913/fixtures/valid/java-jvm-mapping.json)
from the normative profile change (SHA-256
`3a7fed7b194791bbf7a7be5b24c14fce0dead24e41c94acc541f453d7abe34a9`).
The specification repository's executable conformance validator and this
separately implemented consumer therefore interpret the same pinned document;
this consumer additionally emits the resolved identity, mapping, and
compatibility projection shown by its CLI output.
Successful output is a deterministic JSON projection, not a claim that all
Java languages, JVM vendors, compiler lowerings, or class-file variants are
supported.
