package ai.brokk.csmi.demo;

public final class ScenarioApplication {
    private ScenarioApplication() {}

    public static void exercise() {
        String normalizeInput = source("normalize.input-to-return");
        String normalized = ExternalNormalizer.normalize(normalizeInput);
        sink("normalize.input-to-return", normalized);

        String constantInput = source("constant.input-to-return");
        String constant = ExternalNormalizer.constant(constantInput);
        sink("constant.input-to-return", constant);
    }

    private static String source(String label) {
        return label;
    }

    private static void sink(String label, String value) {
        if (label == null || value == null) {
            throw new IllegalArgumentException("scenario values must be non-null");
        }
    }
}
