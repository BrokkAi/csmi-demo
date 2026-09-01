package ai.brokk.csmi.flowdroid;

import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.AdaptedSummaries;
import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.ArtifactIdentity;
import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.Descriptor;
import ai.brokk.csmi.flowdroid.CsmiFlowDroidAdapter.MethodBinding;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import javax.tools.JavaCompiler;
import javax.tools.StandardJavaFileManager;
import javax.tools.StandardLocation;
import javax.tools.ToolProvider;

/** Runs and records one exact pack-off or pack-on shared FlowDroid scenario. */
public final class FlowDroidScenarioCli {
    private static final ObjectMapper MAPPER = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
    private static final String CONSUMER_NAME = "brokkai.csmi.flowdroid";
    private static final String CONSUMER_VERSION = "0.1.0";
    private static final String SEMANTIC_MEDIA_TYPE = "application/vnd.csmi.semantic-model.v0.1+json";
    private static final List<Descriptor> IDENTITY_PREFIX = List.of(
            new Descriptor("namespace", "ai", null),
            new Descriptor("namespace", "brokk", null),
            new Descriptor("namespace", "csmi", null),
            new Descriptor("namespace", "demo", null),
            new Descriptor("type", "ExternalNormalizer", null));

    private FlowDroidScenarioCli() {}

    public static void main(String[] args) throws Exception {
        Arguments arguments = Arguments.parse(args);
        try {
            run(arguments.scenario(), arguments.output(), arguments.pack());
        } catch (Exception failure) {
            ObjectNode result = MAPPER.createObjectNode()
                    .put("resultFormatVersion", "csmi-demo-consumer-result/1")
                    .put("status", "failed");
            result.putObject("consumer").put("name", CONSUMER_NAME).put("version", CONSUMER_VERSION);
            result.putObject("pack").put("state", arguments.pack());
            String code = failure instanceof AdapterException adapter ? adapter.code() : "integrity-failure";
            result.putObject("failure").put("code", code).put("message", failure.getMessage());
            Path absoluteOutput = arguments.output().toAbsolutePath().normalize();
            if (absoluteOutput.getParent() != null) Files.createDirectories(absoluteOutput.getParent());
            MAPPER.writeValue(absoluteOutput.toFile(), result);
            System.exit(2);
        }
    }

    public static void run(Path scenarioDirectory, Path output, String packState) throws Exception {
        if (!Set.of("off", "on").contains(packState)) {
            throw new IllegalArgumentException("pack state must be off or on");
        }
        Path root = scenarioDirectory.toAbsolutePath().normalize();
        Path manifestPath = requireFile(root.resolve("scenario.json"), "scenario manifest");
        JsonNode manifest = MAPPER.readTree(manifestPath.toFile());
        requireText(manifest, "/scenario/status", "materialized");
        Path opaqueJar = verifiedFile(root, manifest, "/binaryArtifact", "opaque library JAR");
        Path applicationSource = verifiedFile(root, manifest, "/applicationArtifact", "analyzer application source");
        Path labelsPath = verifiedFile(root, manifest, "/scenario/labels", "flow labels");
        ArtifactIdentity artifact = new ArtifactIdentity(
                text(manifest, "/binaryArtifact/purl"),
                text(manifest, "/binaryArtifact/digestCoverage"),
                text(manifest, "/binaryArtifact/sha256"));

        AdaptedSummaries adapted = null;
        ObjectNode packIdentity = MAPPER.createObjectNode().put("state", packState);
        if ("on".equals(packState)) {
            adapted = loadPack(root, manifest, artifact);
            packIdentity.set("digest", digestObject(text(manifest, "/csmiPack/packDigest/value")));
            packIdentity.put("semanticDocumentSha256", adapted.trace().semanticDocumentSha256());
        }

        Path compiled = Files.createTempDirectory("csmi-flowdroid-app-");
        try {
            compileApplication(applicationSource, opaqueJar, compiled);
            FlowDroidScenarioRunner.RunResult analysis = new FlowDroidScenarioRunner()
                    .run(compiled, opaqueJar, adapted == null ? null : adapted.wrapper());
            JsonNode labels = MAPPER.readTree(labelsPath.toFile());
            ObjectNode evidence = evidence(
                    manifest,
                    sha256(manifestPath),
                    labels,
                    analysis,
                    artifact,
                    packIdentity,
                    adapted);
            Path absoluteOutput = output.toAbsolutePath().normalize();
            if (absoluteOutput.getParent() != null) Files.createDirectories(absoluteOutput.getParent());
            MAPPER.writeValue(Files.newOutputStream(
                    absoluteOutput, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING), evidence);
        } finally {
            deleteRecursively(compiled);
        }
    }

    private static AdaptedSummaries loadPack(Path root, JsonNode manifest, ArtifactIdentity artifact)
            throws Exception {
        requireText(manifest, "/csmiPack/status", "available");
        requireText(manifest, "/csmiPack/packDigest/algorithm", "sha-256");
        Path packManifestPath = safeFile(root, text(manifest, "/csmiPack/manifestPath"), "CSMI pack manifest");
        verifyDigest(packManifestPath, text(manifest, "/csmiPack/packDigest/value"), "CSMI pack manifest");
        JsonNode packManifest = MAPPER.readTree(packManifestPath.toFile());
        requireText(packManifest, "/documentType", "pack-manifest");
        requireText(packManifest, "/schema", "https://csmi.brokk.ai/schema/0.1/schema.json");
        requireText(packManifest, "/packFormatVersion", "0.1");
        JsonNode resources = packManifest.path("resources");
        if (!resources.isArray() || resources.size() != 1) {
            throw new AdapterException("pack must contain exactly one semantic document");
        }
        JsonNode resource = resources.get(0);
        requireText(resource, "/role", "semantic-document");
        requireText(resource, "/mediaType", SEMANTIC_MEDIA_TYPE);
        Path document = safeFile(packManifestPath.getParent(), text(resource, "/path"), "semantic document");
        if (Files.size(document) != resource.path("size").asLong(-1)) {
            throw new AdapterException("semantic document size mismatch");
        }
        String documentSha256 = text(resource, "/digest/value");
        requireText(resource, "/digest/algorithm", "sha-256");
        verifyDigest(document, documentSha256, "semantic document");
        JsonNode recorded = manifest.at("/csmiPack/resourceDigests/0");
        if (!("pack/" + text(resource, "/path")).equals(text(recorded, "/path"))
                || !SEMANTIC_MEDIA_TYPE.equals(text(recorded, "/mediaType"))
                || resource.path("size").asLong(-1) != recorded.path("size").asLong(-2)
                || !"sha-256".equals(text(recorded, "/algorithm"))
                || !documentSha256.equals(text(recorded, "/value"))) {
            throw new AdapterException("scenario and pack semantic-document digests disagree");
        }
        try (var input = Files.newInputStream(document)) {
            return new CsmiFlowDroidAdapter().adapt(input, documentSha256, artifact, methodBindings());
        }
    }

    static List<MethodBinding> methodBindings() {
        return List.of(binding("constant"), binding("normalize"));
    }

    private static MethodBinding binding(String method) {
        List<Descriptor> descriptors = new java.util.ArrayList<>(IDENTITY_PREFIX);
        descriptors.add(new Descriptor("callable", method, "(java.lang.String)->java.lang.String"));
        return new MethodBinding(
                "ai.brokk.csmi.jvm-symbol",
                "0.1",
                "portable",
                descriptors,
                FlowDroidScenarioRunner.EXTERNAL_CLASS,
                "java.lang.String " + method + "(java.lang.String)",
                List.of("java.lang.String"),
                "java.lang.String");
    }

    static void compileApplication(Path applicationSource, Path opaqueJar, Path destination) throws IOException {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) throw new IllegalStateException("a full JDK is required");
        requireFile(applicationSource, "analyzer application source");
        requireFile(opaqueJar, "opaque library JAR");
        Files.createDirectories(destination);
        try (StandardJavaFileManager files = compiler.getStandardFileManager(null, null, null)) {
            files.setLocationFromPaths(StandardLocation.CLASS_OUTPUT, List.of(destination));
            files.setLocationFromPaths(StandardLocation.CLASS_PATH, List.of(opaqueJar));
            var units = files.getJavaFileObjectsFromPaths(List.of(applicationSource));
            Boolean success = compiler.getTask(
                            null, files, null, List.of("--release", "17", "-g:lines,source"), null, units)
                    .call();
            if (!Boolean.TRUE.equals(success)) throw new IllegalStateException("javac failed for analyzer input");
        }
    }

    private static ObjectNode evidence(
            JsonNode manifest,
            String manifestSha256,
            JsonNode labels,
            FlowDroidScenarioRunner.RunResult analysis,
            ArtifactIdentity artifact,
            ObjectNode packIdentity,
            AdaptedSummaries adapted) {
        ObjectNode root = MAPPER.createObjectNode();
        root.put("resultFormatVersion", "csmi-demo-consumer-result/1");
        root.put("status", "complete");
        root.putObject("consumer").put("name", CONSUMER_NAME).put("version", CONSUMER_VERSION);
        root.putObject("analysis")
                .put("formatVersion", "flowdroid-infoflow/2.15.1")
                .set("configuration", analysisSettings());
        root.withObject("analysis").put("configurationSha256", canonicalSha256(analysisSettings()));
        root.putObject("scenario")
                .put("id", text(manifest, "/scenario/id"))
                .put("version", text(manifest, "/scenario/version"))
                .set("manifest", pathDigest("scenario.json", manifestSha256));
        root.withObject("scenario")
                .set("labels", pathDigest(text(manifest, "/scenario/labels/path"), text(manifest, "/scenario/labels/sha256")));
        ObjectNode artifactNode = root.putObject("artifact").put("purl", artifact.purl());
        artifactNode.putArray("digests")
                .addObject()
                .put("algorithm", "sha-256")
                .put("coverage", artifact.digestCoverage())
                .put("value", artifact.sha256());
        root.set("pack", packIdentity);
        ArrayNode provenance = root.putObject("provenance").putArray("records");
        if (adapted != null) adapted.trace().provenanceRecords().forEach(provenance::add);

        Set<FlowDroidScenarioRunner.LabelFlow> observedPairs = analysis.labelFlows();
        Map<String, Integer> counts = new HashMap<>(Map.of(
                "truePositive", 0, "trueNegative", 0, "falsePositive", 0, "falseNegative", 0));
        ArrayNode flows = root.putArray("flows");
        JsonNode labelFlows = labels.path("flows");
        if (!labelFlows.isArray()) throw new IllegalArgumentException("labels flows must be an array");
        for (JsonNode expected : labelFlows) {
            String sourceLabel = text(expected, "/sourceLabel");
            String sinkLabel = text(expected, "/sinkLabel");
            boolean expectedFlow = expected.path("expected").asBoolean();
            boolean observed = observedPairs.contains(new FlowDroidScenarioRunner.LabelFlow(sourceLabel, sinkLabel));
            String classification;
            if (expectedFlow && observed) classification = "TP";
            else if (expectedFlow) classification = "FN";
            else if (observed) classification = "FP";
            else classification = "TN";
            counts.compute(switch (classification) {
                case "TP" -> "truePositive";
                case "TN" -> "trueNegative";
                case "FP" -> "falsePositive";
                default -> "falseNegative";
            }, (ignored, value) -> value + 1);
            flows.addObject()
                    .put("id", text(expected, "/id"))
                    .put("expectedFlow", expectedFlow)
                    .put("observedFlow", observed)
                    .put("classification", classification);
        }
        for (FlowDroidScenarioRunner.LabelFlow pair : observedPairs) {
            boolean declared = false;
            for (JsonNode expected : labelFlows) {
                if (pair.sourceLabel().equals(text(expected, "/sourceLabel"))
                        && pair.sinkLabel().equals(text(expected, "/sinkLabel"))) {
                    declared = true;
                    break;
                }
            }
            if (!declared) throw new IllegalStateException("FlowDroid observed undeclared label pair " + pair);
        }
        ObjectNode countNode = root.putObject("counts");
        counts.forEach(countNode::put);
        int tp = counts.get("truePositive");
        int fp = counts.get("falsePositive");
        int fn = counts.get("falseNegative");
        ObjectNode metrics = root.putObject("metrics");
        metric(metrics, "precision", tp, tp + fp);
        metric(metrics, "recall", tp, tp + fn);
        root.putObject("termination")
                .put("status", "success")
                .put("flowDroidState", analysis.terminationState())
                .put("externalClassExcludedWithoutBodies", analysis.externalClassExcludedWithoutBodies());
        return root;
    }

    private static ObjectNode analysisSettings() {
        return MAPPER.createObjectNode()
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
                .put("lineNumbers", true)
                .put("javaVersion", System.getProperty("java.version"))
                .put("javaVendor", System.getProperty("java.vendor"))
                .put("mavenVersion", "3.9.11")
                .put("flowDroidVersion", "2.15.1")
                .put("sootVersion", "4.7.1")
                .put("osName", System.getProperty("os.name"))
                .put("osVersion", System.getProperty("os.version"))
                .put("osArch", System.getProperty("os.arch"));
    }

    private static ObjectNode pathDigest(String path, String value) {
        return MAPPER.createObjectNode().put("path", path).put("sha256", value);
    }

    private static ObjectNode digestObject(String value) {
        return MAPPER.createObjectNode().put("algorithm", "sha-256").put("value", value);
    }

    private static void metric(ObjectNode metrics, String name, int numerator, int denominator) {
        ObjectNode metric = metrics.putObject(name)
                .put("defined", denominator > 0)
                .put("numerator", numerator)
                .put("denominator", denominator);
        if (denominator > 0) metric.put("value", (double) numerator / denominator);
    }

    private static String canonicalSha256(JsonNode value) {
        try {
            ObjectMapper canonical = JsonMapper.builder()
                    .enable(com.fasterxml.jackson.databind.MapperFeature.SORT_PROPERTIES_ALPHABETICALLY)
                    .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
                    .build();
            return sha256(canonical.writeValueAsBytes(value));
        } catch (IOException exception) {
            throw new IllegalStateException("cannot canonicalize analysis settings", exception);
        }
    }

    private static Path verifiedFile(Path root, JsonNode manifest, String pointer, String description)
            throws IOException {
        Path path = safeFile(root, text(manifest, pointer + "/path"), description);
        verifyDigest(path, text(manifest, pointer + "/sha256"), description);
        return path;
    }

    private static Path safeFile(Path root, String relativePath, String description) {
        if (relativePath == null || relativePath.contains("\\")) {
            throw new IllegalArgumentException(description + " has an invalid path");
        }
        Path candidate = root.resolve(relativePath).normalize();
        try {
            if (!candidate.toRealPath().startsWith(root.toRealPath())) {
                throw new IllegalArgumentException(description + " escapes its root");
            }
        } catch (IOException exception) {
            throw new IllegalArgumentException(description + " cannot be resolved", exception);
        }
        if (!candidate.startsWith(root.normalize())) {
            throw new IllegalArgumentException(description + " escapes its root");
        }
        return requireFile(candidate, description);
    }

    private static void verifyDigest(Path path, String expected, String description) throws IOException {
        String actual = sha256(path);
        if (!actual.equals(expected)) {
            throw new IllegalArgumentException(description + " SHA-256 mismatch: expected " + expected + ", got " + actual);
        }
    }

    private static Path requireFile(Path path, String description) {
        if (path == null || !Files.isRegularFile(path)) {
            throw new IllegalArgumentException(description + " is not a file: " + path);
        }
        return path;
    }

    private static String text(JsonNode node, String pointer) {
        JsonNode value = node.at(pointer);
        if (!value.isTextual() || value.textValue().isBlank()) {
            throw new IllegalArgumentException("missing text at " + pointer);
        }
        return value.textValue();
    }

    private static void requireText(JsonNode node, String pointer, String expected) {
        if (!expected.equals(text(node, pointer))) {
            throw new IllegalArgumentException("unsupported value at " + pointer);
        }
    }

    private static String sha256(Path path) throws IOException {
        try (var input = Files.newInputStream(path)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[8192];
            for (int read; (read = input.read(buffer)) != -1; ) digest.update(buffer, 0, read);
            return HexFormat.of().formatHex(digest.digest());
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private static String sha256(byte[] bytes) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("SHA-256 is unavailable", exception);
        }
    }

    private static void deleteRecursively(Path root) throws IOException {
        if (!Files.exists(root)) return;
        try (var paths = Files.walk(root)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(path);
        }
    }

    private record Arguments(Path scenario, Path output, String pack) {
        static Arguments parse(String[] args) {
            Map<String, String> values = new HashMap<>();
            for (int i = 0; i < args.length; i += 2) {
                if (i + 1 >= args.length || !args[i].startsWith("--")) {
                    throw new IllegalArgumentException("expected --scenario <path> --output <path> --pack off|on");
                }
                if (values.put(args[i].substring(2), args[i + 1]) != null) {
                    throw new IllegalArgumentException("duplicate option " + args[i]);
                }
            }
            if (!values.keySet().equals(Set.of("scenario", "output", "pack"))) {
                throw new IllegalArgumentException("expected exactly --scenario, --output, and --pack");
            }
            return new Arguments(Path.of(values.get("scenario")), Path.of(values.get("output")), values.get("pack"));
        }
    }
}
