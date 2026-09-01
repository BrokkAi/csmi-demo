# Capability blocker: complete empty Bifrost summary export

The fixture requires complete `procedure-summaries` coverage for
`ExternalNormalizer.constant(String)` with an empty transfer set. That is the
CSMI v0.1 mechanism that makes the absent `parameter[0] -> result[0]` edge a
meaningful negative rather than unknown.

Bifrost's merged CSMI exporter supports that CSMI representation, but its
authored semantic-pack compiler currently rejects the required producer input
before export:

```text
summary.empty at $.shards[1].payload.summaries[0]: a procedure summary must
declare at least one transfer, effect, operation precondition review, result
contract, conditional-result refinement, conditional indirect write,
normal-return refinement, or absent normal continuation
```

Reproduction identity:

- Bifrost repository: `BrokkAi/bifrost-dev`
- commit: `d883a143f31aba973401ad079e313bf080aafe17`
- crate: `brokk-bifrost-analysis 0.10.7`
- API: `export_authored_csmi_pack`
- input: [`producer/bifrost-model.json`](producer/bifrost-model.json)
- failing path: `$.shards[1].payload.summaries[0]`
- diagnostic code: `summary.empty`

The exporter was invoked from a temporary Rust driver that deserialized the
input as `AuthoredSemanticModelPack`, supplied the exact Maven PURL
`pkg:maven/ai.brokk.csmi-demo/external-normalize@1.0.0`, supplied the pinned JAR
SHA-256 from `scenario.json`, and called `export_authored_csmi_pack` with no
creation timestamp.

The following workarounds are intentionally rejected:

- adding a false transfer to the constant-returning method;
- marking the normal continuation absent, which is not true of the fixture;
- adding an unrelated effect or contract merely to satisfy Bifrost's compiler;
- directly constructing Bifrost compiled internals to bypass validation; or
- hand-authoring a CSMI semantic document or manifest.

Until Bifrost accepts and exports a complete empty procedure-summary set, this
scenario has no pack identity and cannot satisfy issue #1's interoperability
acceptance criteria.
