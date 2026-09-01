package ai.brokk.csmi.flowdroid;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import soot.Scene;
import soot.SootClass;
import soot.SootMethod;
import soot.Value;
import soot.jimple.InvokeExpr;
import soot.jimple.Stmt;
import soot.jimple.StringConstant;
import soot.jimple.infoflow.Infoflow;
import soot.jimple.infoflow.InfoflowConfiguration;
import soot.jimple.infoflow.InfoflowConfiguration.CallgraphAlgorithm;
import soot.jimple.infoflow.InfoflowConfiguration.PathReconstructionMode;
import soot.jimple.infoflow.methodSummary.taintWrappers.SummaryTaintWrapper;
import soot.jimple.infoflow.results.DataFlowResult;
import soot.jimple.infoflow.results.InfoflowResults;
import soot.options.Options;

/** Runs the fixed plain-Java FlowDroid scenario without reading evaluator labels. */
public final class FlowDroidScenarioRunner {
    public static final String APPLICATION_CLASS = "ai.brokk.csmi.demo.ScenarioApplication";
    public static final String EXTERNAL_CLASS = "ai.brokk.csmi.demo.ExternalNormalizer";
    public static final String ENTRY_POINT = "<" + APPLICATION_CLASS + ": void exercise()>";
    public static final String SOURCE = "<" + APPLICATION_CLASS + ": java.lang.String source(java.lang.String)>";
    public static final String SINK = "<" + APPLICATION_CLASS + ": void sink(java.lang.String,java.lang.String)>";
    public static final long DATA_FLOW_TIMEOUT_SECONDS = 60;
    public static final long PATH_TIMEOUT_SECONDS = 30;

    public record LabelFlow(String sourceLabel, String sinkLabel) {}

    public record RunResult(
            Set<LabelFlow> labelFlows,
            int terminationState,
            boolean externalClassExcludedWithoutBodies) {
        public RunResult {
            labelFlows = Set.copyOf(labelFlows);
        }
    }

    public RunResult run(Path applicationClasses, Path opaqueJar, SummaryTaintWrapper wrapper) {
        requireDirectory(applicationClasses, "compiled application classes");
        requireFile(opaqueJar, "opaque library JAR");

        InfoflowConfiguration configuration = new InfoflowConfiguration();
        configuration.setCallgraphAlgorithm(CallgraphAlgorithm.CHA);
        configuration.setEnableLineNumbers(true);
        configuration.setMaxThreadNum(1);
        configuration.setDataFlowTimeout(DATA_FLOW_TIMEOUT_SECONDS);
        configuration.getPathConfiguration().setPathReconstructionMode(PathReconstructionMode.NoPaths);
        configuration.getPathConfiguration().setPathReconstructionTimeout(PATH_TIMEOUT_SECONDS);

        Infoflow infoflow = new Infoflow();
        infoflow.setConfig(configuration);
        infoflow.setSootConfig((options, ignored) -> configureSoot(options));
        if (wrapper != null) {
            infoflow.setTaintWrapper(wrapper);
        }

        infoflow.computeInfoflow(
                applicationClasses.toAbsolutePath().toString(),
                opaqueJar.toAbsolutePath().toString(),
                List.of(ENTRY_POINT),
                List.of(SOURCE),
                List.of(SINK));

        InfoflowResults results = infoflow.getResults();
        if (results == null) {
            throw new IllegalStateException("FlowDroid returned no result object");
        }
        if (results.getTerminationState() != InfoflowResults.TERMINATION_SUCCESS) {
            throw new IllegalStateException("FlowDroid terminated unsuccessfully: " + results.getTerminationState());
        }
        if (results.getExceptions() != null && !results.getExceptions().isEmpty()) {
            throw new IllegalStateException("FlowDroid reported analysis exceptions: " + results.getExceptions());
        }

        List<DataFlowResult> orderedResults = new ArrayList<>(results.getResultSet());
        orderedResults.sort(Comparator.comparing(DataFlowResult::toString));
        Set<LabelFlow> labelFlows = new LinkedHashSet<>();
        for (DataFlowResult result : orderedResults) {
            labelFlows.add(extractLabels(result));
        }
        return new RunResult(
                labelFlows,
                results.getTerminationState(),
                externalClassHasNoActiveBodies());
    }

    static LabelFlow extractLabels(DataFlowResult result) {
        if (result == null || result.getSource() == null || result.getSink() == null) {
            throw new IllegalArgumentException("FlowDroid result lacks an exact source or sink");
        }
        return extractLabels(result.getSource().getStmt(), result.getSink().getStmt());
    }

    static LabelFlow extractLabels(Stmt sourceStatement, Stmt sinkStatement) {
        String source = labelArgument(sourceStatement, SOURCE, 0, "source");
        String sink = labelArgument(sinkStatement, SINK, 0, "sink");
        return new LabelFlow(source, sink);
    }

    private static String labelArgument(Stmt statement, String expectedMethod, int index, String kind) {
        if (statement == null || !statement.containsInvokeExpr()) {
            throw new IllegalArgumentException("FlowDroid " + kind + " statement is not an invocation");
        }
        InvokeExpr invocation = statement.getInvokeExpr();
        if (!expectedMethod.equals(invocation.getMethodRef().getSignature())) {
            throw new IllegalArgumentException(
                    "FlowDroid " + kind + " statement invokes unexpected method "
                            + invocation.getMethodRef().getSignature());
        }
        if (invocation.getArgCount() <= index) {
            throw new IllegalArgumentException("FlowDroid " + kind + " statement lacks label argument");
        }
        Value argument = invocation.getArg(index);
        if (!(argument instanceof StringConstant constant) || constant.value == null || constant.value.isBlank()) {
            throw new IllegalArgumentException("FlowDroid " + kind + " label is not a non-empty string constant");
        }
        return constant.value;
    }

    private static void configureSoot(Options options) {
        options.set_exclude(List.of(EXTERNAL_CLASS));
        options.set_no_bodies_for_excluded(true);
        options.set_allow_phantom_refs(true);
        options.set_keep_line_number(true);
    }

    private static boolean externalClassHasNoActiveBodies() {
        SootClass external = Scene.v().getSootClassUnsafe(EXTERNAL_CLASS, false);
        if (external == null) {
            throw new IllegalStateException("opaque external class was not resolved by Soot");
        }
        Collection<SootMethod> methods = external.getMethods();
        if (methods.isEmpty()) {
            throw new IllegalStateException("opaque external class has no resolved methods");
        }
        return methods.stream().noneMatch(SootMethod::hasActiveBody);
    }

    private static void requireDirectory(Path path, String description) {
        if (path == null || !path.toFile().isDirectory()) {
            throw new IllegalArgumentException(description + " is not a directory: " + path);
        }
    }

    private static void requireFile(Path path, String description) {
        if (path == null || !path.toFile().isFile()) {
            throw new IllegalArgumentException(description + " is not a file: " + path);
        }
    }
}
