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

@main def exec(cpgFile: String, semanticsFile: String, packEnabled: Boolean, output: String): Unit =
  importCpg(cpgFile, enhance = false)
  val root = ujson.read(Files.readString(Paths.get(semanticsFile), StandardCharsets.UTF_8)).obj
  require(root("outcome").str == "applied", "CSMI adapter outcome is not applied")
  require(root("joern")("version").str == "4.0.592", "Joern version pin mismatch")
  val custom = root("semantics").arr.toList.map { item =>
    val entry = item.obj
    require(!entry("regex").bool, "CSMI-derived Joern semantics must not use regex matching")
    val mappings = entry("mappings").arr.toList.map { pair =>
      val values = pair.arr
      require(values.length == 2, "FlowSemantic mapping must have two slots")
      (values(0).num.toInt, values(1).num.toInt)
    }
    FlowSemantic.from(entry("methodFullName").str, mappings, regex = false)
  }
  val semantics = if packEnabled then DefaultSemantics().plus(custom) else DefaultSemantics()
  val context = new LayerCreatorContext(cpg)
  new Base().run(context)
  new ControlFlow().run(context)
  new TypeRelations().run(context)
  new CallGraph().run(context)
  new OssDataFlow(OssDataFlowOptions(semantics = semantics)).run(context)

  // Shared issue #1 owns the stable source/sink labels. This query consumes
  // their expected application shape and deliberately does not duplicate labels.
  val observed = cpg.call.nameExact("sink").argument(1).reachableByFlows(cpg.call.nameExact("source")).l
  val result = Obj(
    "schemaVersion" -> 1,
    "joernVersion" -> "4.0.592",
    "packEnabled" -> packEnabled,
    "observedPathCount" -> observed.size,
    "paths" -> Arr.from(observed.map(path => Arr.from(path.elements.map(_.code))))
  )
  Files.writeString(Paths.get(output), result.render() + "\n", StandardCharsets.UTF_8)
