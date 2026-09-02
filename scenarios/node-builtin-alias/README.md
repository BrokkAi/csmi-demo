# Node builtin alias profile scenario

This scenario exercises the CSMI JavaScript/TypeScript and Node profile boundary
without Bifrost or another producer-specific side channel. A dependency-free
Python consumer proves that CommonJS `child_process` and ESM
`node:child_process` select one `node:child_process` runtime symbol only for the
exact Node 22.11.0 distribution. A same-spelled npm package is the near miss.

The Node selector is pinned to the official Linux x64 archive SHA-256 published
in Node's `SHASUMS256.txt`. The archive is not committed. Pass its path to the
consumer verifier to check the external bytes; ordinary tests validate the
pinned identity and profile semantics without network access.

The hand-authored pack is deliberately independent-consumer test input, not
producer-generated interoperability evidence and not a model of `execSync`
behavior. The demonstrated claim is exact identity and alias interpretation.
