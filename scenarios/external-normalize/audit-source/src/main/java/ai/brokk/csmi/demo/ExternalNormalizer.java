package ai.brokk.csmi.demo;

/** Auditable implementation for the opaque binary fixture. Never index this source. */
public final class ExternalNormalizer {
    private ExternalNormalizer() {}

    public static String normalize(String input) {
        return input;
    }

    public static String constant(String input) {
        return "fixed";
    }
}
