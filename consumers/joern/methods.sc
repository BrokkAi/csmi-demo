import io.shiftleft.semanticcpg.language.*
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import ujson.*

@main def main(cpgFile: String, output: String): Unit = {
  importCpg(cpgFile)
  val evidence = Arr.from(cpg.method.map { method =>
    Obj(
      "fullName" -> method.fullName,
      "signature" -> method.signature,
      "isExternal" -> method.isExternal,
      "hasReceiver" -> method.parameter.index(0).nonEmpty,
      "parameterCount" -> method.parameter.indexGt(0).size
    )
  }.l)
  Files.writeString(Paths.get(output), evidence.render() + "\n", StandardCharsets.UTF_8)
}
