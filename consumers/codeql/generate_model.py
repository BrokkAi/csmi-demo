#!/usr/bin/env python3
"""Fail-closed CSMI to CodeQL model-pack adapter for external-normalize.

The generated directory is disposable output. The CSMI pack remains the only
semantic source of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath


SCHEMA = "https://csmi.brokk.ai/schema/0.1/schema.json"
MEDIA_TYPE = "application/vnd.csmi.semantic-model.v0.1+json"
JVM_SCHEME = "ai.brokk.csmi.jvm-symbol"
JVM_SCHEME_VERSION = "0.1"
EXPECTED_CALLABLES = {"normalize", "constant"}
EXPECTED_PURL = "pkg:maven/ai.brokk.csmi-demo/external-normalize@1.0.0"
EXPECTED_DIGEST_COVERAGE = "jar"
EXPECTED_PACKAGE = "ai.brokk.csmi.demo"
EXPECTED_OWNER = "ExternalNormalizer"
PRODUCER_COMMIT = "f91ef53ee28893f23c3a5843d90abd3177bed9df"
EXPECTED_ASSEMBLER = {
    "identifier": "https://bifrost.brokk.ai/csmi-export",
    "version": f"0.1.0+{PRODUCER_COMMIT}",
}
EXPECTED_PRODUCER = {
    "identifier": "https://bifrost.brokk.ai/semantic-pack-producer",
    "version": f"0.10.7+{PRODUCER_COMMIT}",
}


class Unsupported(ValueError):
    pass


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Unsupported(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise Unsupported(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_resource(pack: Path, raw_path: str) -> Path:
    posix = PurePosixPath(raw_path)
    if posix.is_absolute() or ".." in posix.parts or "\x00" in raw_path:
        raise Unsupported(f"unsafe pack resource path: {raw_path!r}")
    resolved = (pack / Path(*posix.parts)).resolve()
    try:
        resolved.relative_to(pack.resolve())
    except ValueError as error:
        raise Unsupported(f"resource escapes pack directory: {raw_path!r}") from error
    return resolved


def select_document(pack: Path, manifest: dict) -> tuple[Path, dict]:
    if manifest.get("documentType") != "pack-manifest":
        raise Unsupported("manifest documentType must be pack-manifest")
    if manifest.get("schema") != SCHEMA or manifest.get("packFormatVersion") != "0.1":
        raise Unsupported("unsupported CSMI pack schema or format version")
    if manifest.get("assembler") != EXPECTED_ASSEMBLER:
        raise Unsupported("unexpected Bifrost assembler identity")
    resources = manifest.get("resources")
    if not isinstance(resources, list) or not resources:
        raise Unsupported("manifest resources must be a non-empty array")
    matches = []
    seen_paths = set()
    for resource in resources:
        raw_path = resource.get("path", "")
        if raw_path in seen_paths:
            raise Unsupported(f"duplicate pack resource path: {raw_path!r}")
        seen_paths.add(raw_path)
        path = safe_resource(pack, resource.get("path", ""))
        if not path.is_file():
            raise Unsupported(f"missing pack resource: {path}")
        if path.stat().st_size != resource.get("size"):
            raise Unsupported(f"pack resource size mismatch: {path}")
        digest = resource.get("digest", {})
        if digest.get("algorithm") != "sha-256" or sha256(path) != digest.get("value"):
            raise Unsupported(f"pack resource digest mismatch: {path}")
        if resource.get("role") == "semantic-document":
            if resource.get("mediaType") != MEDIA_TYPE:
                raise Unsupported("semantic document has an unsupported media type")
            matches.append((path, load_json(path)))
    if len(matches) != 1:
        raise Unsupported(f"expected exactly one semantic document, found {len(matches)}")
    return matches[0]


def exact_provenance(document: dict, artifact: Path) -> dict:
    records = document.get("provenanceRecords")
    if not isinstance(records, list) or len(records) != 1:
        raise Unsupported("expected exactly one semantic-document provenance record")
    expected_input = {
        "digest": {
            "algorithm": "sha-256",
            "coverage": EXPECTED_DIGEST_COVERAGE,
            "value": sha256(artifact),
        },
        "purl": EXPECTED_PURL,
        "role": "target-artifact",
    }
    record = records[0]
    if (
        record.get("id") != "bifrost-export"
        or record.get("generationMethod") != "source-analysis"
        or record.get("invocationId") != f"bifrost:{PRODUCER_COMMIT}"
        or record.get("producer") != EXPECTED_PRODUCER
        or record.get("inputs") != [expected_input]
    ):
        raise Unsupported("semantic-document provenance does not identify the exact Bifrost producer and JAR")
    return record


def exact_selector(model: dict, artifact: Path) -> str:
    actual = sha256(artifact)
    matched = []
    for selector in model.get("artifactSelectors", []):
        digests = selector.get("digests", [])
        if any(
            item.get("algorithm") == "sha-256"
            and item.get("coverage") == EXPECTED_DIGEST_COVERAGE
            and item.get("value") == actual
            for item in digests
        ):
            matched.append(selector.get("purl"))
    if matched != [EXPECTED_PURL]:
        raise Unsupported(
            f"artifact must match exactly one {EXPECTED_DIGEST_COVERAGE!r} selector for "
            f"{EXPECTED_PURL}"
        )
    return matched[0]


def parse_symbol(symbol: dict) -> tuple[str, str, str, str]:
    if (
        symbol.get("scheme") != JVM_SCHEME
        or symbol.get("schemeVersion") != JVM_SCHEME_VERSION
        or symbol.get("stability") != "portable"
    ):
        raise Unsupported(f"unsupported identity for symbol {symbol.get('id')!r}")
    descriptors = symbol.get("descriptors")
    if not isinstance(descriptors, list) or len(descriptors) < 2:
        raise Unsupported("callable descriptor path is incomplete")
    callable_descriptor = descriptors[-1]
    owner_descriptor = descriptors[-2]
    namespaces = descriptors[:-2]
    if (
        callable_descriptor.get("role") != "callable"
        or owner_descriptor.get("role") != "type"
        or any(item.get("role") != "namespace" for item in namespaces)
    ):
        raise Unsupported("callable descriptor path is not namespace*/type/callable")
    package = ".".join(item.get("name", "") for item in namespaces)
    owner = owner_descriptor.get("name")
    name = callable_descriptor.get("name")
    disambiguator = callable_descriptor.get("disambiguator")
    if not all(isinstance(item, str) and item for item in (owner, name, disambiguator)):
        raise Unsupported("callable identity has an empty component")
    match = re.fullmatch(r"\(([^()]*)\)->([^(),]+)", disambiguator)
    if not match:
        raise Unsupported(f"unsupported JVM callable disambiguator: {disambiguator!r}")
    parameters = [] if not match.group(1) else match.group(1).split(",")
    if parameters != ["java.lang.String"] or match.group(2) != "java.lang.String":
        raise Unsupported("scenario callables must have exact (java.lang.String)->java.lang.String identity")
    return package, owner, name, "(String)"


def root(location: dict) -> tuple[str, str, int | None]:
    if location.get("projections"):
        raise Unsupported("CodeQL consumer does not support projected CSMI locations")
    value = location.get("root", {})
    return value.get("phase"), value.get("role"), value.get("position")


def unique_by(values: list, key: str, description: str) -> dict:
    result = {}
    for item in values:
        identity = item.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise Unsupported(f"invalid or duplicate {description}: {identity!r}")
        result[identity] = item
    return result


def build_rows(document: dict, artifact: Path) -> tuple[str, list, list, list]:
    if (
        document.get("documentType") != "semantic-document"
        or document.get("schema") != SCHEMA
        or document.get("semanticModelVersion") != "0.1"
        or document.get("serializationVersion") != "0.1-json"
    ):
        raise Unsupported("unsupported CSMI semantic document version")
    models = document.get("semanticModels", [])
    if len(models) != 1:
        raise Unsupported(f"expected exactly one semantic model, found {len(models)}")
    model = models[0]
    if model.get("vocabularyUses") or model.get("extensionFacts"):
        raise Unsupported("this CodeQL consumer supports no CSMI vocabularies or extension facts")
    purl = exact_selector(model, artifact)
    symbols = unique_by(model.get("symbols", []), "id", "symbol id")
    declarations = unique_by(model.get("declarations", []), "symbol", "declaration symbol")
    summaries = unique_by(model.get("procedureSummaries", []), "callable", "summary callable")
    completeness = {}
    for item in model.get("completenessStatements", []):
        if item.get("family") != "procedure-summaries":
            continue
        callable_id = item.get("scope", {}).get("callable")
        if not isinstance(callable_id, str) or callable_id in completeness:
            raise Unsupported(f"invalid or duplicate procedure-summary completeness scope: {callable_id!r}")
        completeness[callable_id] = item
    summary_rows, neutral_rows, trace = [], [], []
    seen_names = set()
    for symbol_id, summary in summaries.items():
        if symbol_id not in symbols or symbol_id not in declarations:
            raise Unsupported(f"unresolved summary callable: {symbol_id!r}")
        package, owner, name, signature = parse_symbol(symbols[symbol_id])
        if package != EXPECTED_PACKAGE or owner != EXPECTED_OWNER:
            raise Unsupported(f"unexpected scenario callable owner: {package}.{owner}")
        if name not in EXPECTED_CALLABLES or name in seen_names:
            raise Unsupported(f"unexpected or duplicate scenario callable: {name!r}")
        seen_names.add(name)
        declaration = declarations[symbol_id]
        callable_shape = declaration.get("callable", {})
        if (
            declaration.get("category") != "callable"
            or callable_shape.get("kind") != "method"
            or callable_shape.get("receiver") is not None
        ):
            raise Unsupported(
                f"{name} must be receiver-free: CodeQL neutralModel cannot preserve exact-callable "
                "CSMI scope for an overridable instance method"
            )
        parameters = callable_shape.get("parameters")
        results = callable_shape.get("results")
        if (
            not isinstance(parameters, list)
            or len(parameters) != 1
            or parameters[0].get("position") != 0
            or parameters[0].get("required") is not True
            or not isinstance(results, list)
            or len(results) != 1
            or results[0].get("position") != 0
        ):
            raise Unsupported(f"{name} callable shape is not one required parameter and one result")
        if completeness.get(symbol_id, {}).get("status") != "complete":
            raise Unsupported(f"{name} lacks complete procedure-summary coverage")
        if completeness[symbol_id].get("provenance") != ["bifrost-export"]:
            raise Unsupported(f"{name} completeness does not cite exact Bifrost provenance")
        transfers = summary.get("transfers")
        if not isinstance(transfers, list):
            raise Unsupported(f"{name} transfers must be an array")
        if name == "normalize":
            expected = (("input", "parameter", 0), ("output", "result", 0))
            actual = [(root(item.get("source", {})), root(item.get("destination", {}))) for item in transfers]
            if actual != [expected]:
                raise Unsupported("normalize must contain exactly parameter[0] -> result[0]")
            summary_rows.append([package, owner, False, name, signature, "", "Argument[0]", "ReturnValue", "taint", "manual"])
            predicate = "summaryModel"
            codeql_row = summary_rows[-1]
        else:
            if transfers:
                raise Unsupported("constant must have a complete empty transfer set")
            neutral_rows.append([package, owner, name, signature, "summary", "manual"])
            predicate = "neutralModel"
            codeql_row = neutral_rows[-1]
        trace.append(
            {
                "callable": symbol_id,
                "csmi": {
                    "symbol": symbols[symbol_id],
                    "declaration": declaration,
                    "procedureSummary": summary,
                    "completenessStatement": completeness[symbol_id],
                },
                "codeql": {"predicate": predicate, "row": codeql_row},
            }
        )
    if seen_names != EXPECTED_CALLABLES:
        raise Unsupported(f"missing scenario callables: {sorted(EXPECTED_CALLABLES - seen_names)}")
    return purl, summary_rows, neutral_rows, trace


def write_output(
    output: Path,
    purl: str,
    summaries: list,
    neutrals: list,
    trace: list,
    artifact: Path,
    document: Path,
    provenance: dict,
) -> None:
    if output.exists():
        raise Unsupported(f"refusing to overwrite existing output path: {output}")
    output.mkdir(parents=True)
    (output / "codeql-pack.yml").write_text(
        "name: brokkai/csmi-external-normalize-model\nversion: 0.0.0\nlibrary: true\nextensionTargets:\n  codeql/java-all: 9.2.3\ndataExtensions:\n  - csmi.model.yml\n",
        encoding="utf-8",
    )
    extensions = []
    if summaries:
        extensions.append({"addsTo": {"pack": "codeql/java-all", "extensible": "summaryModel"}, "data": summaries})
    if neutrals:
        extensions.append({"addsTo": {"pack": "codeql/java-all", "extensible": "neutralModel"}, "data": neutrals})
    (output / "csmi.model.yml").write_text(json.dumps({"extensions": extensions}, indent=2) + "\n", encoding="utf-8")
    (output / "trace.json").write_text(
        json.dumps(
            {
                "artifact": {"purl": purl, "sha256": sha256(artifact)},
                "provenance": provenance,
                "semanticDocumentSha256": sha256(document),
                "rows": trace,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if not args.artifact.is_file():
            raise Unsupported(f"artifact is not a file: {args.artifact}")
        manifest_path = args.pack / "manifest.json"
        manifest = load_json(manifest_path)
        document_path, document = select_document(args.pack, manifest)
        provenance = exact_provenance(document, args.artifact)
        purl, summaries, neutrals, trace = build_rows(document, args.artifact)
        write_output(
            args.output,
            purl,
            summaries,
            neutrals,
            trace,
            args.artifact,
            document_path,
            provenance,
        )
    except (Unsupported, OSError) as error:
        print(f"CodeQL CSMI generation failed closed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
