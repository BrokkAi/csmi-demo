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
    private static final String CONSUMER_REVISION = "0123456789abcdef0123456789abcdef01234567";

    @TempDir Path temporaryDirectory;

    @Test
    void packOffUsesOnlyCompiledAnalyzerInputAndEmitsExpectedEvidence() throws Exception {
        Path classes = temporaryDirectory.resolve("classes");
        Path opaqueJar = SCENARIO.resolve("analyzer-input/lib/external-normalize-1.0.0.jar");
        FlowDroidPackOffCli.compileApplication(
                SCENARIO.resolve("analyzer-input/src/main/java/ai/brokk/csmi/demo/ScenarioApplication.java"),
                opaqueJar,
                classes);

        assertTrue(Files.isRegularFile(classes.resolve("ai/brokk/csmi/demo/ScenarioApplication.class")));
        assertFalse(Files.exists(classes.resolve("ai/brokk/csmi/demo/ExternalNormalizer.class")),
                "the audit-source implementation must not enter the application classes");

        Path evidencePath = temporaryDirectory.resolve("pack-off.json");
        FlowDroidPackOffCli.run(SCENARIO, evidencePath, CONSUMER_REVISION);
        JsonNode evidence = new ObjectMapper().readTree(evidencePath.toFile());

        assertEquals("complete", evidence.path("status").textValue());
        assertEquals(CONSUMER_REVISION, evidence.at("/consumer/sourceRevision").textValue());
        assertFalse(evidence.at("/pack/enabled").booleanValue());
        assertEquals(0, evidence.at("/counts/truePositive").intValue());
        assertEquals(1, evidence.at("/counts/trueNegative").intValue());
        assertEquals(0, evidence.at("/counts/falsePositive").intValue());
        assertEquals(1, evidence.at("/counts/falseNegative").intValue());
        assertEquals(0, evidence.at("/metrics/precision/denominator").intValue());
        assertFalse(evidence.at("/metrics/precision/defined").booleanValue());
        assertTrue(evidence.at("/metrics/precision/value").isNull());
        assertEquals(0, evidence.at("/termination/flowDroidState").intValue());
        assertTrue(evidence.at("/termination/externalClassExcludedWithoutBodies").booleanValue());
        assertEquals("unavailable", evidence.at("/pack/status").textValue());
        assertEquals("0.1", evidence.at("/csmi/semanticModelVersion").textValue());
        assertEquals(
                "9b09ac88adb5acb4a960b7e7ea613a4a89758cb96f139395231cb926bb929d85",
                evidence.at("/scenario/manifestSha256").textValue());
        assertEquals(1, evidence.at("/metrics/recall/denominator").intValue());
        assertEquals(0.0, evidence.at("/metrics/recall/value").doubleValue());
        assertTrue(evidence.path("flows").findValues("observed").stream().noneMatch(JsonNode::booleanValue),
                "pack-off must miss normalize and retain the constant near-miss as a true negative");
    }

    @Test
    void rejectsChangedFixtureBytesBeforeAnalysis() throws Exception {
        Path copiedScenario = temporaryDirectory.resolve("scenario");
        copyRecursively(SCENARIO, copiedScenario);
        Files.writeString(
                copiedScenario.resolve("analyzer-input/src/main/java/ai/brokk/csmi/demo/ScenarioApplication.java"),
                "\n// changed after manifest creation\n",
                java.nio.file.StandardOpenOption.APPEND);

        IllegalArgumentException failure = assertThrows(
                IllegalArgumentException.class,
                () -> FlowDroidPackOffCli.run(
                        copiedScenario, temporaryDirectory.resolve("result.json"), CONSUMER_REVISION));
        assertTrue(failure.getMessage().contains("analyzer application source SHA-256 mismatch"));
    }

    private static void copyRecursively(Path source, Path destination) throws Exception {
        try (var paths = Files.walk(source)) {
            for (Path path : paths.toList()) {
                Path target = destination.resolve(source.relativize(path));
                if (Files.isDirectory(path)) {
                    Files.createDirectories(target);
                } else {
                    Files.copy(path, target);
                }
            }
        }
    }

    @Test
    void extractsExactStringConstantLabelsAndRejectsNearMiss() {
        SootClass application = Scene.v().getSootClassUnsafe(FlowDroidScenarioRunner.APPLICATION_CLASS, false);
        if (application == null) {
            application = new SootClass(FlowDroidScenarioRunner.APPLICATION_CLASS, Modifier.PUBLIC);
            Scene.v().addClass(application);
        }
        SootMethod sourceMethod = application.getMethodUnsafe("java.lang.String source(java.lang.String)");
        if (sourceMethod == null) {
            RefType stringType = RefType.v("java.lang.String");
            sourceMethod = new SootMethod(
                    "source", List.of(stringType), stringType, Modifier.PRIVATE | Modifier.STATIC);
            application.addMethod(sourceMethod);
        }
        SootMethod sinkMethod = application.getMethodUnsafe("void sink(java.lang.String,java.lang.String)");
        if (sinkMethod == null) {
            RefType stringType = RefType.v("java.lang.String");
            sinkMethod = new SootMethod(
                    "sink", List.of(stringType, stringType), VoidType.v(), Modifier.PRIVATE | Modifier.STATIC);
            application.addMethod(sinkMethod);
        }
        Local resultValue = Jimple.v().newLocal("result", RefType.v("java.lang.String"));
        var sourceStatement = Jimple.v().newAssignStmt(
                resultValue,
                Jimple.v().newStaticInvokeExpr(
                        sourceMethod.makeRef(), StringConstant.v("normalize.input-to-return")));
        var sinkStatement = Jimple.v().newInvokeStmt(Jimple.v().newStaticInvokeExpr(
                sinkMethod.makeRef(),
                StringConstant.v("normalize.input-to-return"),
                resultValue));
        assertEquals(
                new FlowDroidScenarioRunner.LabelFlow(
                        "normalize.input-to-return", "normalize.input-to-return"),
                FlowDroidScenarioRunner.extractLabels(sourceStatement, sinkStatement));

        Local dynamicLabel = Jimple.v().newLocal("dynamicLabel", RefType.v("java.lang.String"));
        var malformedSource = Jimple.v().newAssignStmt(
                resultValue, Jimple.v().newStaticInvokeExpr(sourceMethod.makeRef(), dynamicLabel));
        IllegalArgumentException failure =
                assertThrows(
                        IllegalArgumentException.class,
                        () -> FlowDroidScenarioRunner.extractLabels(malformedSource, sinkStatement));
        assertTrue(failure.getMessage().contains("not a non-empty string constant"));
    }

    @Test
    void cliRejectsPackOnBeforeReadingScenario() {
        IllegalArgumentException failure = assertThrows(
                IllegalArgumentException.class,
                () -> FlowDroidPackOffCli.main(new String[] {
                    "--scenario", SCENARIO.toString(),
                    "--output", temporaryDirectory.resolve("result.json").toString(),
                    "--pack", "on",
                    "--consumer-revision", CONSUMER_REVISION
                }));
        assertTrue(failure.getMessage().contains("only --pack off"));
    }
}
