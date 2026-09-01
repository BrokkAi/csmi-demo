package ai.brokk.csmi.flowdroid;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.ArtifactIdentity;
import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.Descriptor;
import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.MethodBinding;
import java.io.ByteArrayInputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.Test;
import soot.jimple.infoflow.methodSummary.data.summary.MethodFlow;
import soot.jimple.infoflow.methodSummary.data.summary.SourceSinkType;
import soot.Modifier;
import soot.RefType;
import soot.SootClass;
import soot.SootMethod;

final class CsmiFlowDroidAdapterTest {
    private static final String DOC_HASH = "a".repeat(64);
    private static final String ARTIFACT_HASH = "b".repeat(64);
    private static final ArtifactIdentity ARTIFACT =
            new ArtifactIdentity("pkg:maven/ai.brokk.demo/external-normalize@1.0.0", "binary", ARTIFACT_HASH);
    private static final List<Descriptor> DESCRIPTORS = List.of(
            new Descriptor("namespace", "ai", null),
            new Descriptor("namespace", "brokk", null),
            new Descriptor("namespace", "demo", null),
            new Descriptor("type", "ExternalStrings", null),
            new Descriptor("callable", "normalize", "(java.lang.String)->java.lang.String"));
    private static final MethodBinding BINDING = new MethodBinding(
            "org.example.java-source", "0.1", "portable", DESCRIPTORS,
            "ai.brokk.demo.ExternalStrings", "java.lang.String normalize(java.lang.String)",
            List.of("java.lang.String"), "java.lang.String");

    @Test
    void mapsExactParameterToReturnTransfer() throws Exception {
        var adapted = adapt(document("normalize", transfer(), "complete", ARTIFACT_HASH), List.of(BINDING));
        var classFlows = adapted.provider().getClassFlows("ai.brokk.demo.ExternalStrings");
        var flows = classFlows.getMethodSummaries().getFlowsForMethod(BINDING.sootSubSignature());
        assertEquals(1, flows.size());
        MethodFlow flow = flows.iterator().next();
        assertEquals(SourceSinkType.Parameter, flow.source().getType());
        assertEquals(0, flow.source().getParameterIndex());
        assertEquals(SourceSinkType.Return, flow.sink().getType());
        assertEquals(ARTIFACT, adapted.trace().artifact());
        assertEquals(DOC_HASH, adapted.trace().semanticDocumentSha256());
    }

    @Test
    void mapsCompleteEmptySetToExactFlowDroidExclusion() throws Exception {
        var adapted = adapt(document("normalize", "", "complete", ARTIFACT_HASH), List.of(BINDING));
        assertTrue(adapted.provider().isMethodExcluded(BINDING.sootClass(), BINDING.sootSubSignature()));
        assertTrue(adapted.provider().getSummaries().getClassSummaries(BINDING.sootClass())
                .getMethodSummaries().getAllFlows().isEmpty());
        SootClass sootClass = new SootClass(BINDING.sootClass());
        SootMethod method = new SootMethod(
                "normalize", List.of(RefType.v("java.lang.String")), RefType.v("java.lang.String"), Modifier.PUBLIC | Modifier.STATIC);
        sootClass.addMethod(method);
        assertTrue(adapted.wrapper().supportsCallee(method));
    }

    @Test
    void rejectsArtifactDigestMismatch() {
        assertFailure(document("normalize", transfer(), "complete", "c".repeat(64)), List.of(BINDING), "SHA-256");
    }

    @Test
    void rejectsAmbiguousExactBinding() {
        assertFailure(document("normalize", transfer(), "complete", ARTIFACT_HASH), List.of(BINDING, BINDING), "ambiguous");
    }

    @Test
    void rejectsCallableDescriptorNearMiss() {
        var nearMiss = new MethodBinding(
                BINDING.scheme(), BINDING.schemeVersion(), BINDING.stability(),
                List.of(
                        new Descriptor("namespace", "ai", null),
                        new Descriptor("namespace", "brokk", null),
                        new Descriptor("namespace", "demo", null),
                        new Descriptor("type", "ExternalStrings", null),
                        new Descriptor("callable", "normalize", "(java.lang.Object)->java.lang.String")),
                BINDING.sootClass(), BINDING.sootSubSignature(), BINDING.parameterTypes(), BINDING.returnType());
        assertFailure(document("normalize", transfer(), "complete", ARTIFACT_HASH), List.of(nearMiss), "must match exactly");
    }

    @Test
    void rejectsPartialCoverage() {
        assertFailure(document("normalize", transfer(), "partial", ARTIFACT_HASH), List.of(BINDING), "not complete");
    }

    @Test
    void rejectsProjectedTransferInsteadOfDroppingMeaning() {
        String projected = """
          {"source":{"root":{"phase":"input","role":"parameter","position":0},
           "projection":{"scheme":"example.fields","schemeVersion":"0.1","steps":[]}},
           "destination":{"root":{"phase":"output","role":"result","position":0}}}
          """;
        assertFailure(document("normalize", projected, "complete", ARTIFACT_HASH), List.of(BINDING), "projections");
    }

    @Test
    void rejectsOutOfRangeParameterIndex() {
        String outOfRange = """
          {"source":{"root":{"phase":"input","role":"parameter","position":1}},
           "destination":{"root":{"phase":"output","role":"result","position":0}}}
          """;
        assertFailure(document("normalize", outOfRange, "complete", ARTIFACT_HASH), List.of(BINDING), "transfer root");
    }

    @Test
    void rejectsRequiredVocabulary() {
        String json = document("normalize", transfer(), "complete", ARTIFACT_HASH)
                .replace("\"symbols\"", "\"vocabularyUses\":[{\"identifier\":\"example.required\",\"requirement\":\"required\"}],\"symbols\"");
        assertFailure(json, List.of(BINDING), "required vocabulary");
    }

    private static CsmiFlowDroidAdapter.AdaptedSummaries adapt(String json, List<MethodBinding> bindings)
            throws Exception {
        return new CsmiFlowDroidAdapter().adapt(
                new ByteArrayInputStream(json.getBytes(StandardCharsets.UTF_8)), DOC_HASH, ARTIFACT, bindings);
    }

    private static void assertFailure(String json, List<MethodBinding> bindings, String message) {
        AdapterException error = assertThrows(AdapterException.class, () -> adapt(json, bindings));
        assertTrue(error.getMessage().contains(message), error.getMessage());
    }

    private static String transfer() {
        return """
          {"source":{"root":{"phase":"input","role":"parameter","position":0}},
           "destination":{"root":{"phase":"output","role":"result","position":0}}}
          """;
    }

    private static String document(String callable, String transfers, String status, String digest) {
        String transferArray = transfers.isBlank() ? "[]" : "[" + transfers + "]";
        return """
          {
            "documentType":"semantic-document",
            "schema":"https://csmi.brokk.ai/schema/0.1/schema.json",
            "semanticModelVersion":"0.1",
            "serializationVersion":"0.1-json",
            "semanticModels":[{
              "artifactSelectors":[{"purl":"pkg:maven/ai.brokk.demo/external-normalize@1.0.0",
                "digests":[{"algorithm":"sha-256","coverage":"binary","value":"%s"}]}],
              "symbols":[{
                "id":"%s","scheme":"org.example.java-source","schemeVersion":"0.1","stability":"portable",
                "descriptors":[
                  {"role":"namespace","name":"ai"},{"role":"namespace","name":"brokk"},
                  {"role":"namespace","name":"demo"},{"role":"type","name":"ExternalStrings"},
                  {"role":"callable","name":"normalize","disambiguator":"(java.lang.String)->java.lang.String"}
                ]}],
              "declarations":[{"symbol":"%s","category":"callable","callable":{
                "kind":"method","parameters":[{"position":0,"binding":"positional-only","required":true}],
                "results":[{"position":0,"type":{"kind":"unknown"}}]}}],
              "procedureSummaries":[{"callable":"%s","transfers":%s}],
              "completenessStatements":[{"family":"procedure-summaries","scope":{"callable":"%s"},"status":"%s"}]
            }]
          }
          """.formatted(digest, callable, callable, callable, transferArray, callable, status);
    }
}
