package ai.brokk.csmi.flowdroid;

/** A fail-closed CSMI applicability or interpretation error. */
public final class AdapterException extends Exception {
    private final String code;

    public AdapterException(String message) {
        this("unsupported-semantics", message);
    }

    public AdapterException(String code, String message) {
        super(message);
        this.code = code;
    }

    public String code() {
        return code;
    }
}
