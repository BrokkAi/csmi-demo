package ai.brokk.csmi.flowdroid;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import soot.Local;
import soot.Modifier;
import soot.RefType;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.VoidType;
import soot.jimple.Jimple;
import soot.jimple.StringConstant;

final class FlowDroidScenarioRunnerTest {
    private static final Path SCENARIO = Path.of("../..", "scenarios", "external-normalize").toAbsolutePath().normalize();
    private static final String PACK_DIGEST = "97873207ab6ffbc49bafbf4f2f0c08779081529ae1fedabaafb754f60f6fbb76";

    @TempDir Path temporaryDirectory;

    @Test
    void identicalPackOffAndOnRunsEmitContractAndRecoverOnlyPositiveFlow() throws Exception {
        Path offPath = temporaryDirectory.resolve("pack-off.json");
        Path onPath = temporaryDirectory.resolve("pack-on.json");
        FlowDroidScenarioCli.run(SCENARIO, offPath, "off");
        FlowDroidScenarioCli.run(SCENARIO, onPath, "on");
        ObjectMapper mapper = new ObjectMapper();
        JsonNode off = mapper.readTree(offPath.toFile());
        JsonNode on = mapper.readTree(onPath.toFile());

        assertEquals("csmi-demo-consumer-result/1", off.path("resultFormatVersion").textValue());
        assertEquals("complete", off.path("status").textValue());
        assertEquals(off.path("consumer"), on.path("consumer"));
        assertEquals(off.path("analysis"), on.path("analysis"), "only CSMI-derived semantics may be toggled");
        assertEquals(off.path("scenario"), on.path("scenario"));
        assertEquals(off.path("artifact"), on.path("artifact"));
        assertEquals("off", off.at("/pack/state").textValue());
        assertEquals("on", on.at("/pack/state").textValue());
        assertEquals(PACK_DIGEST, on.at("/pack/digest/value").textValue());
        assertEquals("ffff74e5ddb9dfa6f66c3b5c6651d2259fffc43db5549f3ffff1eb2de68fb136",
                on.at("/pack/semanticDocumentSha256").textValue());
        assertCounts(off, 0, 1, 0, 1);
        assertCounts(on, 1, 1, 0, 0);
        assertEquals(List.of("TN", "FN"), off.path("flows").findValuesAsText("classification"));
        assertEquals(List.of("TN", "TP"), on.path("flows").findValuesAsText("classification"));
        assertFalse(off.at("/metrics/precision/defined").booleanValue());
        assertEquals(0, off.at("/metrics/precision/denominator").intValue());
        assertEquals(1.0, on.at("/metrics/precision/value").doubleValue());
        assertEquals(1.0, on.at("/metrics/recall/value").doubleValue());
        assertEquals(0, off.at("/provenance/records").size());
        assertEquals(1, on.at("/provenance/records").size());
        assertEquals("bifrost:f91ef53ee28893f23c3a5843d90abd3177bed9df",
                on.at("/provenance/records/0/invocationId").textValue());
        assertTrue(on.at("/termination/externalClassExcludedWithoutBodies").booleanValue());
    }

    @Test
    void compilesOnlyExactApplicationAndRejectsChangedFixtureBytes() throws Exception {
        Path classes = temporaryDirectory.resolve("classes");
        Path jar = SCENARIO.resolve("analyzer-input/lib/external-normalize-1.0.0.jar");
        FlowDroidScenarioCli.compileApplication(
                SCENARIO.resolve("analyzer-input/src/main/java/ai/brokk/csmi/demo/ScenarioApplication.java"), jar, classes);
        assertTrue(Files.isRegularFile(classes.resolve("ai/brokk/csmi/demo/ScenarioApplication.class")));
        assertFalse(Files.exists(classes.resolve("ai/brokk/csmi/demo/ExternalNormalizer.class")));

        Path copy = temporaryDirectory.resolve("scenario");
        copyRecursively(SCENARIO, copy);
        Files.writeString(copy.resolve("pack/semantic-document.json"), "\n", java.nio.file.StandardOpenOption.APPEND);
        AdapterException failure = assertThrows(
                AdapterException.class,
                () -> FlowDroidScenarioCli.run(copy, temporaryDirectory.resolve("result.json"), "on"));
        assertTrue(failure.getMessage().contains("semantic document size mismatch"));
    }

    @Test
    void exactBindingsMatchSharedJvmIdentityAndRejectNearMiss() {
        var bindings = FlowDroidScenarioCli.methodBindings();
        assertEquals(List.of("constant", "normalize"), bindings.stream()
                .map(binding -> binding.descriptors().get(binding.descriptors().size() - 1).name())
                .toList());
        assertEquals("ai.brokk.csmi.jvm-symbol", bindings.get(0).scheme());
        assertEquals("java.lang.String constant(java.lang.String)", bindings.get(0).sootSubSignature());
        assertThrows(IllegalArgumentException.class, () -> new CsmiFlowDroidAdapter.MethodBinding(
                bindings.get(0).scheme(), bindings.get(0).schemeVersion(), bindings.get(0).stability(),
                bindings.get(0).descriptors(), bindings.get(0).sootClass(),
                "java.lang.String constant(java.lang.Object)", bindings.get(0).parameterTypes(), bindings.get(0).returnType()));
    }

    @Test
    void extractsExactStringConstantLabelsAndRejectsNearMiss() {
        SootClass application = Scene.v().getSootClassUnsafe(FlowDroidScenarioRunner.APPLICATION_CLASS, false);
        if (application == null) {
            application = new SootClass(FlowDroidScenarioRunner.APPLICATION_CLASS, Modifier.PUBLIC);
            Scene.v().addClass(application);
        }
        RefType stringType = RefType.v("java.lang.String");
        SootMethod source = application.getMethodUnsafe("java.lang.String source(java.lang.String)");
        if (source == null) {
            source = new SootMethod("source", List.of(stringType), stringType, Modifier.PRIVATE | Modifier.STATIC);
            application.addMethod(source);
        }
        SootMethod sink = application.getMethodUnsafe("void sink(java.lang.String,java.lang.String)");
        if (sink == null) {
            sink = new SootMethod("sink", List.of(stringType, stringType), VoidType.v(), Modifier.PRIVATE | Modifier.STATIC);
            application.addMethod(sink);
        }
        Local resultValue = Jimple.v().newLocal("result", stringType);
        var sourceStatement = Jimple.v().newAssignStmt(resultValue, Jimple.v().newStaticInvokeExpr(
                source.makeRef(), StringConstant.v("normalize.input-to-return")));
        var sinkStatement = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                sink.makeRef(), StringConstant.v("normalize.input-to-return"), resultValue));
        assertEquals(new FlowDroidScenarioRunner.LabelFlow(
                "normalize.input-to-return", "normalize.input-to-return"),
                FlowDroidScenarioRunner.extractLabels(sourceStatement, sinkStatement));
        Local dynamic = Jimple.v().newLocal("dynamic", stringType);
        var malformed = Jimple.v().newAssignStmt(
                resultValue, Jimple.v().newStaticInvokeExpr(source.makeRef(), dynamic));
        assertThrows(IllegalArgumentException.class, () -> FlowDroidScenarioRunner.extractLabels(malformed, sinkStatement));
    }

    private static void assertCounts(JsonNode result, int tp, int tn, int fp, int fn) {
        assertEquals(tp, result.at("/counts/truePositive").intValue());
        assertEquals(tn, result.at("/counts/trueNegative").intValue());
        assertEquals(fp, result.at("/counts/falsePositive").intValue());
        assertEquals(fn, result.at("/counts/falseNegative").intValue());
    }

    private static void copyRecursively(Path source, Path destination) throws Exception {
        try (var paths = Files.walk(source)) {
            for (Path path : paths.toList()) {
                Path target = destination.resolve(source.relativize(path));
                if (Files.isDirectory(path)) Files.createDirectories(target);
                else Files.copy(path, target);
            }
        }
    }
}
