import io.joern.dataflowengineoss.DefaultSemantics
import io.joern.dataflowengineoss.language.*
import io.joern.dataflowengineoss.layers.dataflows.OssDataFlow
import io.joern.dataflowengineoss.layers.dataflows.OssDataFlowOptions
import io.joern.dataflowengineoss.semanticsloader.FlowSemantic
import io.shiftleft.semanticcpg.language.*
import io.shiftleft.semanticcpg.layers.LayerCreatorContext
import io.joern.x2cpg.layers.{Base, CallGraph, ControlFlow, TypeRelations}
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import ujson.*

@main def main(cpgFile: String, labelsFile: String, semanticsFile: String, packEnabled: Boolean, output: String): Unit = {
  importCpg(cpgFile, enhance = false)
  val custom =
    if packEnabled then
      val root = ujson.read(Files.readString(Paths.get(semanticsFile), StandardCharsets.UTF_8)).obj
      require(root("outcome").str == "applied", "CSMI adapter outcome is not applied")
      require(root("joern")("version").str == "4.0.592", "Joern version pin mismatch")
      root("semantics").arr.toList.map { item =>
        val entry = item.obj
        require(!entry("regex").bool, "CSMI-derived Joern semantics must not use regex matching")
        val mappings = entry("mappings").arr.toList.map { pair =>
          val values = pair.arr
          require(values.length == 2, "FlowSemantic mapping must have two slots")
          (values(0).num.toInt, values(1).num.toInt)
        }
        FlowSemantic.from(entry("methodFullName").str, mappings, regex = false)
      }
    else List.empty[FlowSemantic]
  val semantics = if packEnabled then DefaultSemantics().plus(custom) else DefaultSemantics()
  val context = new LayerCreatorContext(cpg)
  new Base().run(context)
  new ControlFlow().run(context)
  new TypeRelations().run(context)
  new CallGraph().run(context)
  // Pass the semantics explicitly as both the layer option and its implicit
  // constructor argument. Joern 4.0.592 otherwise selects the constructor's
  // default semantics in this script context and silently ignores the option.
  new OssDataFlow(OssDataFlowOptions(semantics = semantics))(semantics).run(context)

  val labels = ujson.read(Files.readString(Paths.get(labelsFile), StandardCharsets.UTF_8)).obj
  val observations = labels("flows").arr.map { rawFlow =>
    val flow = rawFlow.obj
    val sourceLabel = flow("sourceLabel").str
    val sinkLabel = flow("sinkLabel").str
    val sourceCode = s"\"$sourceLabel\""
    val sinkCode = s"\"$sinkLabel\""
    val sources = cpg.call.nameExact("source").where(_.argument(1).codeExact(sourceCode))
    val sinks = cpg.call.nameExact("sink").where(_.argument(1).codeExact(sinkCode)).argument(2)
    val paths = sinks.reachableByFlows(sources).l
    Obj(
      "id" -> flow("id").str,
      "observed" -> paths.nonEmpty,
      "pathCount" -> paths.size,
      "paths" -> Arr.from(paths.map(path => Arr.from(path.elements.map(_.code))))
    )
  }
  val result = Obj(
    "schemaVersion" -> 1,
    "joernVersion" -> "4.0.592",
    "packEnabled" -> packEnabled,
    "flows" -> Arr.from(observations)
  )
  Files.writeString(Paths.get(output), result.render() + "\n", StandardCharsets.UTF_8)
}
