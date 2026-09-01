/**
 * @name CSMI external-normalize labeled flows
 * @description Reports shared scenario labels whose source reaches the labeled sink value.
 * @kind table
 * @id brokkai/csmi-demo/external-normalize
 */

import java
import semmle.code.java.dataflow.TaintTracking

private predicate isExactSource(Method method) {
  method.hasQualifiedName("ai.brokk.csmi.demo", "ScenarioApplication", "source") and
  method.isStatic() and
  method.getNumberOfParameters() = 1 and
  method.getParameterType(0) instanceof TypeString and
  method.getReturnType() instanceof TypeString
}

private predicate isExactSink(Method method) {
  method.hasQualifiedName("ai.brokk.csmi.demo", "ScenarioApplication", "sink") and
  method.isStatic() and
  method.getNumberOfParameters() = 2 and
  method.getParameterType(0) instanceof TypeString and
  method.getParameterType(1) instanceof TypeString and
  method.getReturnType() instanceof VoidType
}

private predicate isExactSourceCall(MethodCall call) {
  isExactSource(call.getMethod()) and call.getNumArgument() = 1
}

private predicate isExactSinkCall(MethodCall call) {
  isExactSink(call.getMethod()) and call.getNumArgument() = 2
}

private predicate hasSameLiteralLabel(MethodCall sourceCall, MethodCall sinkCall) {
  exists(StringLiteral sourceLabel, StringLiteral sinkLabel |
    sourceLabel = sourceCall.getArgument(0) and
    sinkLabel = sinkCall.getArgument(0) and
    sourceLabel.getValue() = sinkLabel.getValue()
  )
}

private string getSinkLabel(MethodCall sinkCall) {
  exists(StringLiteral label |
    label = sinkCall.getArgument(0) and
    result = label.getValue()
  )
}

private module ScenarioConfig implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node source) {
    exists(MethodCall call |
      isExactSourceCall(call) and
      source.asExpr() = call
    )
  }

  predicate isSink(DataFlow::Node sink) {
    exists(MethodCall call |
      isExactSinkCall(call) and
      sink.asExpr() = call.getArgument(1)
    )
  }
}

private module ScenarioFlow = TaintTracking::Global<ScenarioConfig>;

from MethodCall sourceCall, MethodCall sinkCall
where
  isExactSourceCall(sourceCall) and
  isExactSinkCall(sinkCall) and
  hasSameLiteralLabel(sourceCall, sinkCall) and
  ScenarioFlow::flow(DataFlow::exprNode(sourceCall), DataFlow::exprNode(sinkCall.getArgument(1)))
select getSinkLabel(sinkCall) as flowLabel
