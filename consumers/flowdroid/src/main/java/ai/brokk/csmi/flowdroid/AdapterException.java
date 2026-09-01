package ai.brokk.csmi.flowdroid;

/** A fail-closed CSMI applicability or interpretation error. */
public final class AdapterException extends Exception {
    public AdapterException(String message) {
        super(message);
    }
}
