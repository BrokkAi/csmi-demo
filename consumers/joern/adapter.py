#!/usr/bin/env python3
"""Fail-closed CSMI 0.1 to Joern FlowSemantic projection.

This adapter intentionally implements only the unprojected core procedure-summary
subset needed by the shared external-normalize scenario. Unsupported CSMI input is
reported, never approximated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CSMI_SCHEMA = "https://csmi.brokk.ai/schema/0.1/schema.json"
SEMANTIC_MEDIA_TYPE = "application/vnd.csmi.semantic-model.v0.1+json"
JOERN_IDENTITY_SCHEME = "io.joern.method-full-name"
JOERN_IDENTITY_VERSION = "4.0.592"
# Issue #1 owns the scenario's exact Java identity scheme. It has not landed,
# so production support remains empty rather than blessing an example scheme.
SUPPORTED_SYMBOL_SCHEMES: frozenset[tuple[str, str]] = frozenset()
HEX_256 = re.compile(r"^[0-9a-f]{64}$")


class AdapterError(Exception):
    def __init__(self, outcome: str, code: str, message: str):
        super().__init__(message)
        self.outcome = outcome
        self.code = code
        self.message = message


def fail(outcome: str, code: str, message: str) -> None:
    raise AdapterError(outcome, code, message)


def object_(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("invalid", "invalid-structure", f"{where} must be an object")
    return value


def array(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        fail("invalid", "invalid-structure", f"{where} must be an array")
    return value


def string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        fail("invalid", "invalid-structure", f"{where} must be a non-empty string")
    return value


def canonical_json(value: Any) -> bytes:
    """JCS-compatible encoding for the integer-only CSMI core subset.

    Floating-point JSON is rejected because reproducing ECMAScript number
    serialization with Python's encoder would not establish RFC 8785 bytes.
    """
    def reject_floats(item: Any) -> None:
        if isinstance(item, float):
            fail("integrity-failure", "unsupported-jcs-number", "floating-point JCS values are unsupported")
        if isinstance(item, list):
            for child in item:
                reject_floats(child)
        elif isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    fail("invalid", "invalid-json-key", "JSON object keys must be strings")
                reject_floats(child)

    reject_floats(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def read_json(path: Path, where: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        fail("integrity-failure", "resource-unreadable", f"cannot read {where}: {error}")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_resource(pack_dir: Path, logical_path: str) -> Path:
    if not logical_path or "\\" in logical_path or "\x00" in logical_path:
        fail("invalid", "unsafe-resource-path", f"unsafe resource path: {logical_path!r}")
    candidate = Path(logical_path)
    if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
        fail("invalid", "unsafe-resource-path", f"unsafe resource path: {logical_path!r}")
    resolved_root = pack_dir.resolve()
    resolved = (pack_dir / candidate).resolve()
    if resolved_root not in resolved.parents:
        fail("invalid", "unsafe-resource-path", f"resource escapes pack: {logical_path!r}")
    return resolved


@dataclass(frozen=True)
class LoadedPack:
    digest: str
    document_digest: str
    document: dict[str, Any]


def load_pack(pack_dir: Path, expected_digest: str | None) -> LoadedPack:
    manifest_path = pack_dir / "manifest.json"
    manifest = object_(read_json(manifest_path, "pack manifest"), "pack manifest")
    if manifest.get("documentType") != "pack-manifest" or manifest.get("packFormatVersion") != "0.1":
        fail("unsupported", "unsupported-pack-format", "expected a CSMI 0.1 pack manifest")
    if manifest.get("schema") != CSMI_SCHEMA:
        fail("unsupported", "unsupported-schema", "pack uses an unsupported schema")

    raw_manifest = manifest_path.read_bytes()
    canonical_manifest = canonical_json(manifest)
    if raw_manifest != canonical_manifest:
        fail("integrity-failure", "noncanonical-manifest", "manifest bytes are not RFC 8785 canonical for the supported subset")
    pack_digest = sha256(canonical_manifest)
    if expected_digest is not None and pack_digest != expected_digest:
        fail("integrity-failure", "pack-digest-mismatch", "computed pack digest does not match the expected digest")

    semantic: list[tuple[str, str, dict[str, Any]]] = []
    for index, raw_descriptor in enumerate(array(manifest.get("resources"), "manifest.resources")):
        descriptor = object_(raw_descriptor, f"manifest.resources[{index}]")
        logical_path = string(descriptor.get("path"), f"manifest.resources[{index}].path")
        resource_path = safe_resource(pack_dir, logical_path)
        try:
            resource_bytes = resource_path.read_bytes()
        except OSError as error:
            fail("integrity-failure", "missing-resource", f"cannot read {logical_path}: {error}")
        digest_record = object_(descriptor.get("digest"), f"manifest.resources[{index}].digest")
        if digest_record.get("algorithm") != "sha-256":
            fail("unsupported", "unsupported-resource-digest", f"unsupported resource digest for {logical_path}")
        declared_digest = string(digest_record.get("value"), f"manifest.resources[{index}].digest.value")
        if not HEX_256.fullmatch(declared_digest) or sha256(resource_bytes) != declared_digest:
            fail("integrity-failure", "resource-digest-mismatch", f"digest mismatch for {logical_path}")
        declared_size = descriptor.get("size")
        if not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size < 0:
            fail("invalid", "invalid-resource-size", f"invalid size for {logical_path}")
        if declared_size != len(resource_bytes):
            fail("integrity-failure", "resource-size-mismatch", f"size mismatch for {logical_path}")
        if descriptor.get("role") == "semantic-document":
            if descriptor.get("mediaType") != SEMANTIC_MEDIA_TYPE:
                fail("unsupported", "unsupported-media-type", f"unsupported semantic media type for {logical_path}")
            document = object_(read_json(resource_path, logical_path), logical_path)
            if resource_bytes != canonical_json(document):
                fail("integrity-failure", "noncanonical-resource", f"{logical_path} is not canonical JSON")
            semantic.append((logical_path, declared_digest, document))

    if len(semantic) != 1:
        fail("unsupported", "unsupported-pack-shape", "this consumer requires exactly one semantic document")
    _, document_digest, document = semantic[0]
    return LoadedPack(pack_digest, document_digest, document)


def comparable_digest(selector: dict[str, Any], candidate: dict[str, Any]) -> str:
    candidate_digests = {
        (entry.get("algorithm"), entry.get("coverage")): entry.get("value")
        for entry in array(candidate.get("digests"), "artifact.digests")
        if isinstance(entry, dict)
    }
    saw_comparable = False
    for raw_digest in array(selector.get("digests", []), "artifact selector digests"):
        digest = object_(raw_digest, "artifact selector digest")
        key = (digest.get("algorithm"), digest.get("coverage"))
        if key in candidate_digests:
            saw_comparable = True
            if candidate_digests[key] != digest.get("value"):
                return "not-matched"
    if selector.get("digests") and not saw_comparable:
        return "indeterminate"
    return "matched"


def applicability(model: dict[str, Any], candidate: dict[str, Any]) -> None:
    outcomes: list[str] = []
    for raw_selector in array(model.get("artifactSelectors"), "semanticModel.artifactSelectors"):
        selector = object_(raw_selector, "artifact selector")
        if selector.get("purl") != candidate.get("purl"):
            outcomes.append("not-matched")
            continue
        outcomes.append(comparable_digest(selector, candidate))
    if "matched" in outcomes:
        return
    if "indeterminate" in outcomes:
        fail("incomplete", "artifact-applicability-indeterminate", "artifact evidence cannot establish applicability")
    fail("inapplicable", "artifact-not-matched", "CSMI artifact identity does not match the analyzed dependency")


def check_symbol_scope(model: dict[str, Any], symbol: dict[str, Any], candidate: dict[str, Any]) -> None:
    scope = {"artifactSelectors": symbol.get("artifactSelectors", model.get("artifactSelectors"))}
    applicability(scope, candidate)


def symbols_by_id(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw_symbol in array(model.get("symbols"), "semanticModel.symbols"):
        symbol = object_(raw_symbol, "symbol")
        symbol_id = string(symbol.get("id"), "symbol.id")
        if symbol_id in result:
            fail("invalid", "duplicate-symbol", f"duplicate symbol id: {symbol_id}")
        result[symbol_id] = symbol
    return result


def declarations_by_symbol(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw_declaration in array(model.get("declarations", []), "semanticModel.declarations"):
        declaration = object_(raw_declaration, "declaration")
        symbol = string(declaration.get("symbol"), "declaration.symbol")
        if symbol in result:
            fail("invalid", "duplicate-declaration", f"duplicate declaration for {symbol}")
        result[symbol] = declaration
    return result


def joern_identity(model: dict[str, Any], symbol: dict[str, Any], candidate: dict[str, Any]) -> str:
    check_symbol_scope(model, symbol, candidate)
    scheme = (symbol.get("scheme"), symbol.get("schemeVersion"))
    if scheme not in SUPPORTED_SYMBOL_SCHEMES:
        fail("unsupported", "unsupported-symbol-scheme", f"unsupported callable symbol scheme {scheme[0]} {scheme[1]}")
    matches = [
        identity
        for identity in array(symbol.get("externalIdentities", []), "symbol.externalIdentities")
        if isinstance(identity, dict)
        and identity.get("scheme") == JOERN_IDENTITY_SCHEME
        and identity.get("version") == JOERN_IDENTITY_VERSION
    ]
    if len(matches) != 1:
        fail("unsupported", "missing-exact-joern-identity", "callable must have one pinned Joern external identity")
    return string(matches[0].get("value"), "Joern external identity value")


def resolve_method(full_name: str, methods: list[Any]) -> dict[str, Any]:
    matches = [method for method in methods if isinstance(method, dict) and method.get("fullName") == full_name]
    if len(matches) != 1:
        code = "unresolved-method-identity" if not matches else "ambiguous-method-identity"
        fail("incomplete", code, f"expected exactly one Joern METHOD with fullName {full_name!r}, found {len(matches)}")
    method = matches[0]
    if method.get("isExternal") is not True:
        fail("inapplicable", "method-not-external", f"Joern METHOD {full_name!r} is not external")
    return method


def callable_shape(declaration: dict[str, Any]) -> dict[str, Any]:
    if declaration.get("category") != "callable":
        fail("invalid", "summary-target-not-callable", "procedure summary target is not callable")
    shape = declaration.get("callable")
    if not isinstance(shape, dict):
        fail("incomplete", "missing-callable-shape", "complete callable shape is required")
    parameters = array(shape.get("parameters"), "callable.parameters")
    results = array(shape.get("results"), "callable.results")
    if [item.get("position") for item in parameters if isinstance(item, dict)] != list(range(len(parameters))):
        fail("invalid", "invalid-parameter-positions", "parameter positions must be contiguous from zero")
    if [item.get("position") for item in results if isinstance(item, dict)] != list(range(len(results))):
        fail("invalid", "invalid-result-positions", "result positions must be contiguous from zero")
    return shape


def slot(location: dict[str, Any], shape: dict[str, Any], phase: str) -> int:
    if location.get("projections") not in (None, []):
        fail("unsupported", "unsupported-projection", "Joern consumer supports only unprojected boundary locations")
    root = object_(location.get("root"), "boundary root")
    if root.get("phase") != phase:
        fail("invalid", "invalid-transfer-phase", f"transfer {phase} boundary has the wrong phase")
    role = root.get("role")
    if role == "receiver":
        if "position" in root or not isinstance(shape.get("receiver"), dict):
            fail("invalid", "invalid-receiver-root", "receiver root is unindexed and requires a declared receiver")
        return 0
    if role == "parameter":
        position = root.get("position")
        if not isinstance(position, int) or isinstance(position, bool) or not 0 <= position < len(shape["parameters"]):
            fail("invalid", "invalid-parameter-root", "parameter root does not exist in callable shape")
        return position + 1
    if phase == "output" and role == "result":
        position = root.get("position")
        if position != 0 or len(shape["results"]) != 1:
            fail("unsupported", "unsupported-result-shape", "Joern FlowSemantic projection requires exactly result[0]")
        return -1
    fail("unsupported", "unsupported-boundary-root", f"unsupported {phase} boundary role: {role!r}")


def complete_summary_symbols(model: dict[str, Any]) -> set[str]:
    complete: set[str] = set()
    seen: set[str] = set()
    for raw_statement in array(model.get("completenessStatements", []), "semanticModel.completenessStatements"):
        statement = object_(raw_statement, "completeness statement")
        if statement.get("family") != "procedure-summaries":
            continue
        scope = object_(statement.get("scope"), "procedure summary completeness scope")
        callable_id = string(scope.get("callable"), "procedure summary completeness callable")
        if callable_id in seen:
            fail("invalid", "duplicate-completeness", f"duplicate procedure-summary completeness for {callable_id}")
        seen.add(callable_id)
        status = statement.get("status")
        if status == "complete":
            if statement.get("limitations"):
                fail("invalid", "complete-with-limitations", "complete coverage cannot have limitations")
            complete.add(callable_id)
        elif status in ("partial", "unknown"):
            fail("incomplete", f"{status}-procedure-summary", f"procedure summary coverage for {callable_id} is {status}")
        else:
            fail("unsupported", "unsupported-coverage-status", f"unsupported completeness status: {status!r}")
    return complete


def method_shape_matches(shape: dict[str, Any], method: dict[str, Any]) -> None:
    expected_receiver = isinstance(shape.get("receiver"), dict)
    if method.get("hasReceiver") is not expected_receiver:
        fail("incomplete", "receiver-shape-mismatch", "Joern receiver shape does not match CSMI")
    parameter_count = method.get("parameterCount")
    if parameter_count != len(shape["parameters"]):
        fail("incomplete", "parameter-shape-mismatch", "Joern parameter count does not match CSMI")


def project(loaded: LoadedPack, artifact: dict[str, Any], methods: list[Any]) -> dict[str, Any]:
    document = loaded.document
    if (
        document.get("documentType") != "semantic-document"
        or document.get("schema") != CSMI_SCHEMA
        or document.get("semanticModelVersion") != "0.1"
        or document.get("serializationVersion") != "0.1-json"
    ):
        fail("unsupported", "unsupported-semantic-document", "expected a CSMI 0.1 JSON semantic document")
    models = array(document.get("semanticModels"), "semanticModels")
    if len(models) != 1:
        fail("unsupported", "unsupported-model-count", "this consumer requires exactly one semantic model")
    model = object_(models[0], "semantic model")
    if model.get("vocabularyUses"):
        fail("unsupported", "unsupported-vocabulary", "this consumer supports no required or optional vocabulary projection")
    applicability(model, artifact)

    symbols = symbols_by_id(model)
    declarations = declarations_by_symbol(model)
    complete = complete_summary_symbols(model)
    summaries = array(model.get("procedureSummaries", []), "semanticModel.procedureSummaries")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_summary in summaries:
        summary = object_(raw_summary, "procedure summary")
        callable_id = string(summary.get("callable"), "procedureSummary.callable")
        if callable_id in seen:
            fail("invalid", "duplicate-summary", f"duplicate procedure summary for {callable_id}")
        seen.add(callable_id)
        if callable_id not in complete:
            fail("incomplete", "summary-not-complete", f"procedure summary for {callable_id} is not complete")
        symbol = symbols.get(callable_id)
        declaration = declarations.get(callable_id)
        if symbol is None or declaration is None:
            fail("invalid", "unresolved-summary-target", f"summary target {callable_id} is not declared")
        full_name = joern_identity(model, symbol, artifact)
        method = resolve_method(full_name, methods)
        shape = callable_shape(declaration)
        method_shape_matches(shape, method)
        mappings: set[tuple[int, int]] = set()
        for raw_transfer in array(summary.get("transfers"), "procedureSummary.transfers"):
            transfer = object_(raw_transfer, "transfer")
            source = slot(object_(transfer.get("source"), "transfer.source"), shape, "input")
            destination = slot(object_(transfer.get("destination"), "transfer.destination"), shape, "output")
            mappings.add((source, destination))
        output.append({"methodFullName": full_name, "regex": False, "mappings": [list(item) for item in sorted(mappings)]})

    missing = complete - seen
    if missing:
        fail("invalid", "complete-summary-missing", f"complete summary scopes lack summaries: {sorted(missing)}")
    if not output:
        fail("incomplete", "no-projected-summaries", "no complete Joern-projectable procedure summaries were present")
    return {
        "schemaVersion": 1,
        "outcome": "applied",
        "joern": {"version": JOERN_IDENTITY_VERSION, "identityScheme": JOERN_IDENTITY_SCHEME},
        "csmi": {"packDigest": loaded.digest, "semanticDocumentDigest": loaded.document_digest},
        "semantics": output,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--methods", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-pack-digest")
    args = parser.parse_args(argv)
    result: dict[str, Any]
    exit_code = 0
    try:
        loaded = load_pack(args.pack, args.expected_pack_digest)
        artifact = object_(read_json(args.artifact, "artifact evidence"), "artifact evidence")
        methods = array(read_json(args.methods, "Joern method evidence"), "Joern method evidence")
        result = project(loaded, artifact, methods)
    except AdapterError as error:
        result = {"schemaVersion": 1, "outcome": error.outcome, "diagnostic": {"code": error.code, "message": error.message}}
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json(result) + b"\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
