package ai.brokk.csmi.flowdroid;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import soot.SootMethod;
import soot.jimple.infoflow.methodSummary.data.provider.MemorySummaryProvider;
import soot.jimple.infoflow.methodSummary.data.sourceSink.ConstraintType;
import soot.jimple.infoflow.methodSummary.data.sourceSink.FlowSink;
import soot.jimple.infoflow.methodSummary.data.sourceSink.FlowSource;
import soot.jimple.infoflow.methodSummary.data.summary.ClassSummaries;
import soot.jimple.infoflow.methodSummary.data.summary.IsAliasType;
import soot.jimple.infoflow.methodSummary.data.summary.MethodFlow;
import soot.jimple.infoflow.methodSummary.data.summary.MethodSummaries;
import soot.jimple.infoflow.methodSummary.data.summary.SourceSinkType;
import soot.jimple.infoflow.methodSummary.taintWrappers.SummaryTaintWrapper;

/** Strict, deliberately narrow CSMI 0.1 to FlowDroid 2.15.1 summary adapter. */
public final class CsmiFlowDroidAdapter {
    private static final String SCHEMA = "https://csmi.brokk.ai/schema/0.1/schema.json";
    private final ObjectMapper mapper = new ObjectMapper();

    public record ArtifactIdentity(String purl, String digestCoverage, String sha256) {
        public ArtifactIdentity {
            if (purl == null || purl.isBlank() || digestCoverage == null || digestCoverage.isBlank()
                    || sha256 == null || !sha256.matches("[0-9a-f]{64}")) {
                throw new IllegalArgumentException("exact PURL, digest coverage, and lowercase SHA-256 are required");
            }
        }
    }

    /** One resolver-proven mapping. Descriptors are ordered and compared exactly. */
    public record MethodBinding(
            String scheme,
            String schemeVersion,
            String stability,
            List<Descriptor> descriptors,
            String sootClass,
            String sootSubSignature,
            List<String> parameterTypes,
            String returnType) {
        public MethodBinding {
            descriptors = List.copyOf(descriptors);
            parameterTypes = List.copyOf(parameterTypes);
            if (descriptors.isEmpty() || !"callable".equals(descriptors.get(descriptors.size() - 1).role())) {
                throw new IllegalArgumentException("binding must end in an exact callable descriptor");
            }
            String expected = returnType + " " + descriptors.get(descriptors.size() - 1).name()
                    + "(" + String.join(",", parameterTypes) + ")";
            if (!expected.equals(sootSubSignature)) {
                throw new IllegalArgumentException("Soot subsignature disagrees with the bound callable shape");
            }
        }
    }

    public record Descriptor(String role, String name, String disambiguator) {}

    public record Trace(String semanticDocumentSha256, ArtifactIdentity artifact, Set<String> callableSymbols) {
        public Trace {
            callableSymbols = Set.copyOf(callableSymbols);
        }
    }

    public record AdaptedSummaries(MemorySummaryProvider provider, SummaryTaintWrapper wrapper, Trace trace) {}

    public AdaptedSummaries adapt(
            InputStream csmiJson,
            String semanticDocumentSha256,
            ArtifactIdentity artifact,
            List<MethodBinding> bindings) throws IOException, AdapterException {
        if (semanticDocumentSha256 == null || !semanticDocumentSha256.matches("[0-9a-f]{64}")) {
            throw new AdapterException("an exact lowercase semantic-document SHA-256 is required");
        }
        JsonNode root = mapper.readTree(csmiJson);
        requireText(root, "documentType", "semantic-document");
        requireText(root, "schema", SCHEMA);
        requireText(root, "semanticModelVersion", "0.1");
        requireText(root, "serializationVersion", "0.1-json");

        JsonNode models = requiredArray(root, "semanticModels");
        List<JsonNode> applicable = new ArrayList<>();
        for (JsonNode model : models) {
            if (matchesArtifact(model, artifact)) {
                applicable.add(model);
            }
        }
        if (applicable.size() != 1) {
            throw new AdapterException("expected exactly one applicable semantic model, found " + applicable.size());
        }

        JsonNode model = applicable.get(0);
        rejectRequiredVocabularies(model);
        Map<String, JsonNode> symbols = uniqueById(requiredArray(model, "symbols"), "symbol");
        Map<String, JsonNode> declarations = uniqueByField(requiredArray(model, "declarations"), "symbol", "declaration");
        Map<String, JsonNode> summaries = uniqueByField(requiredArray(model, "procedureSummaries"), "callable", "summary");
        Map<String, String> coverage = readCoverage(model);
        Map<String, MethodBinding> resolved = resolveBindings(symbols, bindings);
        if (resolved.size() != bindings.size() || !resolved.keySet().equals(summaries.keySet())) {
            throw new AdapterException("configured bindings, resolved callables, and summaries must match exactly");
        }

        ClassSummaries classSummaries = new ClassSummaries();
        Set<String> adaptedSymbols = new HashSet<>();
        for (Map.Entry<String, JsonNode> entry : summaries.entrySet()) {
            String symbolId = entry.getKey();
            MethodBinding binding = resolved.get(symbolId);
            if (binding == null) {
                throw new AdapterException("no exact Soot binding for callable " + symbolId);
            }
            validateDeclaration(symbolId, declarations.get(symbolId), binding);
            if (!"complete".equals(coverage.get(symbolId))) {
                throw new AdapterException("procedure-summary coverage is not complete for " + symbolId);
            }
            MethodSummaries methodSummaries = classSummaries
                    .getOrCreateClassSummaries(binding.sootClass())
                    .getMethodSummaries();
            JsonNode transfers = requiredArray(entry.getValue(), "transfers");
            if (transfers.isEmpty()) {
                // FlowDroid otherwise applies its unknown-call behavior. Exclusion is its
                // native explicit no-summary-propagation mechanism for this exact method.
                methodSummaries.addExcludedMethod(binding.sootSubSignature());
            } else {
                for (JsonNode transfer : transfers) {
                    int parameter = validateSupportedTransfer(transfer, binding);
                    FlowSource source = new FlowSource(
                            SourceSinkType.Parameter, parameter, binding.parameterTypes().get(parameter), ConstraintType.FALSE);
                    FlowSink sink = new FlowSink(
                            SourceSinkType.Return, -1, binding.returnType(), false, ConstraintType.FALSE);
                    methodSummaries.addFlow(new MethodFlow(
                            binding.sootSubSignature(), source, sink, IsAliasType.FALSE,
                            true, false, false, null, true, false));
                }
            }
            adaptedSymbols.add(symbolId);
        }
        if (!coverage.keySet().equals(summaries.keySet())) {
            throw new AdapterException("complete coverage and procedure-summary scopes must match exactly");
        }
        MemorySummaryProvider provider = new MemorySummaryProvider(classSummaries);
        return new AdaptedSummaries(
                provider,
                new ExactSummaryTaintWrapper(provider),
                new Trace(semanticDocumentSha256, artifact, adaptedSymbols));
    }

    /** Makes FlowDroid select its exact-method exclusion for a complete empty set. */
    private static final class ExactSummaryTaintWrapper extends SummaryTaintWrapper {
        private final MemorySummaryProvider provider;

        ExactSummaryTaintWrapper(MemorySummaryProvider provider) {
            super(provider);
            this.provider = provider;
        }

        @Override
        public boolean supportsCallee(SootMethod method) {
            return super.supportsCallee(method)
                    || provider.isMethodExcluded(method.getDeclaringClass().getName(), method.getSubSignature());
        }
    }

    private boolean matchesArtifact(JsonNode model, ArtifactIdentity artifact) throws AdapterException {
        JsonNode selectors = requiredArray(model, "artifactSelectors");
        boolean matched = false;
        for (JsonNode selector : selectors) {
            if (!artifact.purl().equals(text(selector, "purl"))) continue;
            JsonNode digests = requiredArray(selector, "digests");
            boolean digestMatched = false;
            for (JsonNode digest : digests) {
                if ("sha-256".equals(text(digest, "algorithm"))
                        && artifact.digestCoverage().equals(text(digest, "coverage"))
                        && artifact.sha256().equals(text(digest, "value"))) {
                    digestMatched = true;
                }
            }
            if (!digestMatched) throw new AdapterException("artifact PURL matched but exact SHA-256 did not");
            if (matched) throw new AdapterException("duplicate exact artifact selectors are ambiguous");
            matched = true;
        }
        return matched;
    }

    private void rejectRequiredVocabularies(JsonNode model) throws AdapterException {
        JsonNode uses = model.path("vocabularyUses");
        if (uses.isMissingNode()) return;
        if (!uses.isArray()) throw new AdapterException("vocabularyUses must be an array");
        for (JsonNode use : uses) {
            if ("required".equals(text(use, "requirement"))) {
                throw new AdapterException("required vocabulary is unsupported: " + text(use, "identifier"));
            }
        }
    }

    private Map<String, MethodBinding> resolveBindings(Map<String, JsonNode> symbols, List<MethodBinding> bindings)
            throws AdapterException {
        Map<String, MethodBinding> result = new HashMap<>();
        for (Map.Entry<String, JsonNode> entry : symbols.entrySet()) {
            JsonNode symbol = entry.getValue();
            List<MethodBinding> matches = bindings.stream().filter(b -> matchesSymbol(symbol, b)).toList();
            if (matches.size() > 1) throw new AdapterException("ambiguous Soot binding for " + entry.getKey());
            if (matches.size() == 1) {
                if (symbol.has("artifactSelectors")) {
                    throw new AdapterException("callable-specific artifact selectors are unsupported");
                }
                result.put(entry.getKey(), matches.get(0));
            }
        }
        return result;
    }

    private boolean matchesSymbol(JsonNode symbol, MethodBinding binding) {
        if (!binding.scheme().equals(text(symbol, "scheme"))
                || !binding.schemeVersion().equals(text(symbol, "schemeVersion"))
                || !binding.stability().equals(text(symbol, "stability"))) return false;
        JsonNode descriptors = symbol.path("descriptors");
        if (!descriptors.isArray() || descriptors.size() != binding.descriptors().size()) return false;
        for (int i = 0; i < descriptors.size(); i++) {
            Descriptor expected = binding.descriptors().get(i);
            JsonNode actual = descriptors.get(i);
            if (!expected.role().equals(text(actual, "role")) || !expected.name().equals(text(actual, "name"))) return false;
            String actualDisambiguator = text(actual, "disambiguator");
            if (expected.disambiguator() == null ? actualDisambiguator != null : !expected.disambiguator().equals(actualDisambiguator)) return false;
        }
        return true;
    }

    private void validateDeclaration(String symbol, JsonNode declaration, MethodBinding binding) throws AdapterException {
        if (declaration == null || !"callable".equals(text(declaration, "category"))) {
            throw new AdapterException("missing callable declaration for " + symbol);
        }
        JsonNode callable = declaration.path("callable");
        if (!"method".equals(text(callable, "kind"))) {
            throw new AdapterException("FlowDroid adapter requires a Java method declaration for " + symbol);
        }
        JsonNode parameters = requiredArray(callable, "parameters");
        if (parameters.size() != binding.parameterTypes().size()) throw new AdapterException("parameter count mismatch for " + symbol);
        for (int i = 0; i < parameters.size(); i++) {
            if (parameters.get(i).path("position").asInt(-1) != i) throw new AdapterException("noncontiguous parameter positions for " + symbol);
        }
        JsonNode results = requiredArray(callable, "results");
        if (results.size() != 1 || results.get(0).path("position").asInt(-1) != 0) {
            throw new AdapterException("FlowDroid adapter requires exactly result[0] for " + symbol);
        }
    }

    private int validateSupportedTransfer(JsonNode transfer, MethodBinding binding) throws AdapterException {
        JsonNode source = transfer.path("source");
        JsonNode destination = transfer.path("destination");
        if (source.has("projection") || destination.has("projection")) throw new AdapterException("projections are unsupported");
        JsonNode from = source.path("root");
        JsonNode to = destination.path("root");
        int parameter = from.path("position").asInt(-1);
        if (!"input".equals(text(from, "phase")) || !"parameter".equals(text(from, "role"))
                || parameter < 0 || parameter >= binding.parameterTypes().size()
                || !"output".equals(text(to, "phase")) || !"result".equals(text(to, "role"))
                || to.path("position").asInt(-1) != 0) {
            throw new AdapterException("unsupported or invalid transfer root");
        }
        return parameter;
    }

    private Map<String, String> readCoverage(JsonNode model) throws AdapterException {
        Map<String, String> result = new HashMap<>();
        JsonNode statements = requiredArray(model, "completenessStatements");
        for (JsonNode statement : statements) {
            if (!"procedure-summaries".equals(text(statement, "family"))) continue;
            String callable = text(statement.path("scope"), "callable");
            if (callable == null) throw new AdapterException("procedure-summary completeness lacks callable scope");
            if (result.put(callable, text(statement, "status")) != null) throw new AdapterException("duplicate completeness scope for " + callable);
        }
        return result;
    }

    private Map<String, JsonNode> uniqueById(JsonNode values, String kind) throws AdapterException {
        return uniqueByField(values, "id", kind);
    }

    private Map<String, JsonNode> uniqueByField(JsonNode values, String field, String kind) throws AdapterException {
        Map<String, JsonNode> result = new HashMap<>();
        for (JsonNode value : values) {
            String key = text(value, field);
            if (key == null || result.put(key, value) != null) throw new AdapterException("missing or duplicate " + kind + " " + key);
        }
        return result;
    }

    private static JsonNode requiredArray(JsonNode node, String field) throws AdapterException {
        JsonNode value = node.path(field);
        if (!value.isArray()) throw new AdapterException(field + " must be an array");
        return value;
    }

    private static void requireText(JsonNode node, String field, String expected) throws AdapterException {
        if (!expected.equals(text(node, field))) throw new AdapterException("unsupported " + field);
    }

    private static String text(JsonNode node, String field) {
        JsonNode value = node.get(field);
        return value != null && value.isTextual() ? value.textValue() : null;
    }
}
