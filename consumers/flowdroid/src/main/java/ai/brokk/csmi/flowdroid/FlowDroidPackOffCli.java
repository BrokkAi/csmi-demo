package ai.brokk.csmi.flowdroid;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.tools.JavaCompiler;
import javax.tools.StandardJavaFileManager;
import javax.tools.StandardLocation;
import javax.tools.ToolProvider;

/** Command-line pack-off evidence producer for the fixed shared scenario. */
public final class FlowDroidPackOffCli {
    private static final ObjectMapper MAPPER = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);

    private FlowDroidPackOffCli() {}

    public static void main(String[] args) throws Exception {
        Arguments arguments = Arguments.parse(args);
        if (!"off".equals(arguments.pack())) {
            throw new IllegalArgumentException("only --pack off is supported until a generated CSMI pack is available");
        }
        run(arguments.scenario(), arguments.output(), arguments.consumerRevision());
    }

    public static void run(Path scenarioDirectory, Path output, String consumerRevision) throws Exception {
        if (consumerRevision == null || !consumerRevision.matches("[0-9a-f]{40,64}")) {
            throw new IllegalArgumentException("consumer revision must be a full lowercase Git object ID");
        }
        Path scenarioRoot = scenarioDirectory.toAbsolutePath().normalize();
        Path manifestPath = requireFile(scenarioRoot.resolve("scenario.json"), "scenario manifest");
        JsonNode scenario = MAPPER.readTree(manifestPath.toFile());
        Path opaqueJar = verifiedFile(
                scenarioRoot,
                requiredText(scenario, "/binaryArtifact/path"),
                requiredText(scenario, "/binaryArtifact/sha256"),
                "opaque library JAR");
        Path applicationSource = verifiedFile(
                scenarioRoot,
                requiredText(scenario, "/applicationArtifact/path"),
                requiredText(scenario, "/applicationArtifact/sha256"),
                "analyzer application source");
        Path labelsPath = verifiedFile(
                scenarioRoot,
                requiredText(scenario, "/scenario/labels/path"),
                requiredText(scenario, "/scenario/labels/sha256"),
                "flow labels");

        Path compiled = Files.createTempDirectory("csmi-flowdroid-app-");
        try {
            compileApplication(applicationSource, opaqueJar, compiled);
            FlowDroidScenarioRunner.RunResult analysis =
                    new FlowDroidScenarioRunner().run(compiled, opaqueJar, null);
            JsonNode labels = MAPPER.readTree(labelsPath.toFile());
            ObjectNode evidence = evidence(scenario, sha256(manifestPath), labels, analysis, consumerRevision);
            Path absoluteOutput = output.toAbsolutePath().normalize();
            if (absoluteOutput.getParent() != null) {
                Files.createDirectories(absoluteOutput.getParent());
            }
            MAPPER.writeValue(Files.newOutputStream(
                    absoluteOutput, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING), evidence);
        } finally {
            deleteRecursively(compiled);
        }
    }

    static void compileApplication(Path applicationSource, Path opaqueJar, Path destination) throws IOException {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            throw new IllegalStateException("a full JDK with javax.tools.JavaCompiler is required");
        }
        requireFile(applicationSource, "analyzer application source");
        requireFile(opaqueJar, "opaque library JAR");
        Files.createDirectories(destination);
        try (StandardJavaFileManager files = compiler.getStandardFileManager(null, null, null)) {
            files.setLocationFromPaths(StandardLocation.CLASS_OUTPUT, List.of(destination));
            files.setLocationFromPaths(StandardLocation.CLASS_PATH, List.of(opaqueJar));
            var units = files.getJavaFileObjectsFromPaths(List.of(applicationSource));
            List<String> options = List.of("--release", "17", "-g:lines,source");
            Boolean success = compiler.getTask(null, files, null, options, null, units).call();
            if (!Boolean.TRUE.equals(success)) {
                throw new IllegalStateException("javac failed for analyzer-input sources");
            }
        }
    }

    private static ObjectNode evidence(
            JsonNode manifest,
            String manifestSha256,
            JsonNode labels,
            FlowDroidScenarioRunner.RunResult analysis,
            String consumerRevision) {
        ObjectNode root = MAPPER.createObjectNode();
        root.put("resultFormatVersion", 1);
        root.put("status", "complete");
        root.putObject("consumer")
                .put("id", "flowdroid")
                .put("version", "2.15.1")
                .put("adapter", "csmi-flowdroid-consumer/0.1.0-SNAPSHOT")
                .put("sourceRevision", consumerRevision);
        root.putObject("scenario")
                .put("id", requiredText(manifest, "/scenario/id"))
                .put("version", requiredText(manifest, "/scenario/version"))
                .put("manifestSha256", manifestSha256)
                .put("labelsSha256", requiredText(manifest, "/scenario/labels/sha256"))
                .put("applicationSha256", requiredText(manifest, "/applicationArtifact/sha256"));
        root.putObject("artifact")
                .put("purl", requiredText(manifest, "/binaryArtifact/purl"))
                .put("digestCoverage", requiredText(manifest, "/binaryArtifact/digestCoverage"))
                .put("sha256", requiredText(manifest, "/binaryArtifact/sha256"));
        root.putObject("pack")
                .put("enabled", false)
                .put("status", requiredText(manifest, "/csmiPack/status"))
                .putNull("packDigest");
        root.putObject("csmi")
                .put("semanticModelVersion", requiredText(manifest, "/normativeCsmi/semanticModelVersion"))
                .put("serializationVersion", requiredText(manifest, "/normativeCsmi/serializationVersion"))
                .put("packFormatVersion", requiredText(manifest, "/normativeCsmi/packFormatVersion"));
        root.putObject("analyzer")
                .put("name", "FlowDroid Infoflow")
                .put("version", "2.15.1")
                .put("sootVersion", "4.7.1");
        root.putObject("environment")
                .put("javaVersion", System.getProperty("java.version"))
                .put("javaVendor", System.getProperty("java.vendor"))
                .put("mavenVersion", "3.9.11")
                .put("osName", System.getProperty("os.name"))
                .put("osVersion", System.getProperty("os.version"))
                .put("osArch", System.getProperty("os.arch"));
        root.putObject("analysisSettings")
                .put("entryPoint", FlowDroidScenarioRunner.ENTRY_POINT)
                .put("source", FlowDroidScenarioRunner.SOURCE)
                .put("sink", FlowDroidScenarioRunner.SINK)
                .put("callgraphAlgorithm", "CHA")
                .put("maxThreads", 1)
                .put("dataFlowTimeoutSeconds", FlowDroidScenarioRunner.DATA_FLOW_TIMEOUT_SECONDS)
                .put("pathReconstruction", "NoPaths")
                .put("pathTimeoutSeconds", FlowDroidScenarioRunner.PATH_TIMEOUT_SECONDS)
                .put("excludedClass", FlowDroidScenarioRunner.EXTERNAL_CLASS)
                .put("noBodiesForExcluded", true)
                .put("lineNumbers", true);

        Set<FlowDroidScenarioRunner.LabelFlow> observedPairs = analysis.labelFlows();
        Map<String, Integer> counts = new HashMap<>(Map.of("tp", 0, "tn", 0, "fp", 0, "fn", 0));
        ArrayNode flows = root.putArray("flows");
        for (JsonNode expectedFlow : requiredArray(labels, "flows")) {
            String sourceLabel = requiredText(expectedFlow, "/sourceLabel");
            String sinkLabel = requiredText(expectedFlow, "/sinkLabel");
            boolean expected = requiredBoolean(expectedFlow, "expected");
            boolean observed = observedPairs.contains(new FlowDroidScenarioRunner.LabelFlow(sourceLabel, sinkLabel));
            String classification = expected ? (observed ? "tp" : "fn") : (observed ? "fp" : "tn");
            counts.compute(classification, (ignored, value) -> value + 1);
            flows.addObject()
                    .put("id", requiredText(expectedFlow, "/id"))
                    .put("sourceLabel", sourceLabel)
                    .put("sinkLabel", sinkLabel)
                    .put("expected", expected)
                    .put("observed", observed)
                    .put("classification", classification);
        }
        for (FlowDroidScenarioRunner.LabelFlow pair : observedPairs) {
            boolean declared = false;
            for (JsonNode expectedFlow : requiredArray(labels, "flows")) {
                if (pair.sourceLabel().equals(requiredText(expectedFlow, "/sourceLabel"))
                        && pair.sinkLabel().equals(requiredText(expectedFlow, "/sinkLabel"))) {
                    declared = true;
                    break;
                }
            }
            if (!declared) {
                throw new IllegalStateException("FlowDroid observed undeclared label pair " + pair);
            }
        }

        ObjectNode countNode = root.putObject("counts");
        countNode.put("truePositive", counts.get("tp"));
        countNode.put("trueNegative", counts.get("tn"));
        countNode.put("falsePositive", counts.get("fp"));
        countNode.put("falseNegative", counts.get("fn"));
        countNode.put("total", counts.values().stream().mapToInt(Integer::intValue).sum());
        ObjectNode metrics = root.putObject("metrics");
        metric(metrics, "precision", counts.get("tp"), counts.get("tp") + counts.get("fp"));
        metric(metrics, "recall", counts.get("tp"), counts.get("tp") + counts.get("fn"));
        metric(metrics, "accuracy", counts.get("tp") + counts.get("tn"),
                counts.values().stream().mapToInt(Integer::intValue).sum());
        root.putObject("termination")
                .put("status", "success")
                .put("flowDroidState", analysis.terminationState())
                .put("externalClassExcludedWithoutBodies", analysis.externalClassExcludedWithoutBodies());
        return root;
    }

    private static void metric(ObjectNode metrics, String name, int numerator, int denominator) {
        ObjectNode metric = metrics.putObject(name);
        metric.put("numerator", numerator);
        metric.put("denominator", denominator);
        metric.put("defined", denominator != 0);
        if (denominator == 0) {
            metric.putNull("value");
        } else {
            metric.put("value", (double) numerator / denominator);
        }
    }

    private static JsonNode requiredArray(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isArray()) {
            throw new IllegalArgumentException(field + " must be an array");
        }
        return value;
    }

    private static String requiredText(JsonNode node, String pointer) {
        JsonNode value = node.at(pointer);
        if (!value.isTextual() || value.textValue().isBlank()) {
            throw new IllegalArgumentException("missing text at " + pointer);
        }
        return value.textValue();
    }

    private static boolean requiredBoolean(JsonNode node, String field) {
        JsonNode value = node.path(field);
        if (!value.isBoolean()) {
            throw new IllegalArgumentException(field + " must be boolean");
        }
        return value.booleanValue();
    }

    private static Path requireFile(Path path, String description) {
        if (!Files.isRegularFile(path)) {
            throw new IllegalArgumentException(description + " is not a file: " + path);
        }
        return path;
    }

    private static Path verifiedFile(Path root, String relativePath, String expectedSha256, String description)
            throws IOException {
        Path candidate = root.resolve(relativePath).normalize();
        if (!candidate.startsWith(root)) {
            throw new IllegalArgumentException(description + " escapes scenario root: " + relativePath);
        }
        requireFile(candidate, description);
        String actualSha256 = sha256(candidate);
        if (!expectedSha256.equals(actualSha256)) {
            throw new IllegalArgumentException(
                    description + " SHA-256 mismatch: expected " + expectedSha256 + ", got " + actualSha256);
        }
        return candidate;
    }

    private static String sha256(Path path) throws IOException {
        final MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
        try (var input = Files.newInputStream(path)) {
            byte[] buffer = new byte[8192];
            for (int read; (read = input.read(buffer)) != -1; ) {
                digest.update(buffer, 0, read);
            }
        }
        return java.util.HexFormat.of().formatHex(digest.digest());
    }

    private static void deleteRecursively(Path root) throws IOException {
        if (!Files.exists(root)) return;
        try (var paths = Files.walk(root)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) {
                Files.delete(path);
            }
        }
    }

    private record Arguments(Path scenario, Path output, String pack, String consumerRevision) {
        static Arguments parse(String[] args) {
            Map<String, String> values = new HashMap<>();
            for (int i = 0; i < args.length; i += 2) {
                if (i + 1 >= args.length || !args[i].startsWith("--")) {
                    throw new IllegalArgumentException(
                            "expected --scenario <path> --output <path> --pack off --consumer-revision <git-id>");
                }
                if (values.put(args[i].substring(2), args[i + 1]) != null) {
                    throw new IllegalArgumentException("duplicate option " + args[i]);
                }
            }
            if (!values.keySet().equals(Set.of("scenario", "output", "pack", "consumer-revision"))) {
                throw new IllegalArgumentException(
                        "expected exactly --scenario, --output, --pack, and --consumer-revision");
            }
            return new Arguments(
                    Path.of(values.get("scenario")),
                    Path.of(values.get("output")),
                    values.get("pack"),
                    values.get("consumer-revision"));
        }
    }
}
