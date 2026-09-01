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
JVM_SYMBOL_SCHEME = ("ai.brokk.csmi.jvm-symbol", "0.1")
SUPPORTED_SYMBOL_SCHEMES: frozenset[tuple[str, str]] = frozenset({JVM_SYMBOL_SCHEME})
HEX_256 = re.compile(r"^[0-9a-f]{64}$")
CSMI_SCHEMA_SHA256 = "99d280864662e947421e0a840d7dbbd81bdf635fedaefaa7e44fa63bd49221b8"


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


def validate_schema(instance: Any, where: str) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import best_match
    except ImportError:
        fail("unsupported", "schema-validator-unavailable", "install consumers/joern/requirements-validation.txt")
    schema_path = Path(__file__).with_name("schema") / "csmi-0.1.json"
    schema_bytes = schema_path.read_bytes()
    if sha256(schema_bytes) != CSMI_SCHEMA_SHA256:
        fail("integrity-failure", "schema-digest-mismatch", "pinned CSMI 0.1 schema digest mismatch")
    schema = json.loads(schema_bytes)
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance))
    if errors:
        error = best_match(errors)
        path = "$" + "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in error.absolute_path)
        fail("invalid", "schema-invalid", f"{where} {path}: {error.message}")


@dataclass(frozen=True)
class LoadedPack:
    digest: str
    document_digest: str
    document: dict[str, Any]


def load_pack(pack_dir: Path, expected_digest: str | None) -> LoadedPack:
    manifest_path = pack_dir / "manifest.json"
    manifest = object_(read_json(manifest_path, "pack manifest"), "pack manifest")
    validate_schema(manifest, "pack manifest")
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
            validate_schema(document, logical_path)
            if resource_bytes != canonical_json(document):
                fail("integrity-failure", "noncanonical-resource", f"{logical_path} is not canonical JSON")
            semantic.append((logical_path, declared_digest, document))

    if len(semantic) != 1:
        fail("unsupported", "unsupported-pack-shape", "this consumer requires exactly one semantic document")
    _, document_digest, document = semantic[0]
    return LoadedPack(pack_digest, document_digest, document)


def load_scenario_pack(scenario_path: Path) -> tuple[LoadedPack, dict[str, Any]]:
    manifest = object_(read_json(scenario_path, "scenario manifest"), "scenario manifest")
    pack = object_(manifest.get("csmiPack"), "scenario.csmiPack")
    manifest_path = pack.get("manifestPath")
    digest_record = pack.get("packDigest")
    if not isinstance(manifest_path, str) or not manifest_path or not isinstance(digest_record, dict):
        fail("unavailable", "pack-unavailable", "scenario has no generated CSMI pack identity")
    if digest_record.get("algorithm") != "sha-256":
        fail("unsupported", "unsupported-pack-digest", "scenario pack digest must use sha-256")
    expected_digest = string(digest_record.get("value"), "scenario.csmiPack.packDigest.value")
    resolved_manifest = safe_resource(scenario_path.parent, manifest_path)
    if resolved_manifest.name != "manifest.json":
        fail("unsupported", "unsupported-manifest-name", "CSMI pack manifest must be named manifest.json")
    binary = object_(manifest.get("binaryArtifact"), "scenario.binaryArtifact")
    binary_path = safe_resource(scenario_path.parent, string(binary.get("path"), "scenario.binaryArtifact.path"))
    try:
        actual_binary_digest = sha256(binary_path.read_bytes())
    except OSError as error:
        fail("integrity-failure", "artifact-unreadable", f"cannot read analyzed dependency: {error}")
    declared_binary_digest = string(binary.get("sha256"), "scenario.binaryArtifact.sha256")
    if not HEX_256.fullmatch(declared_binary_digest) or actual_binary_digest != declared_binary_digest:
        fail("integrity-failure", "artifact-digest-mismatch", "analyzed dependency does not match scenario identity")
    artifact = {
        "purl": string(binary.get("purl"), "scenario.binaryArtifact.purl"),
        "digests": [{
            "algorithm": "sha-256",
            "coverage": string(binary.get("digestCoverage"), "scenario.binaryArtifact.digestCoverage"),
            "value": declared_binary_digest,
        }],
    }
    return load_pack(resolved_manifest.parent, expected_digest), artifact


def selector_outcome(selector: dict[str, Any], candidate: dict[str, Any]) -> str:
    # This consumer supports only exact, unqualified PURLs. It deliberately
    # leaves ranges and qualifiers uninterpretable instead of implementing a
    # partial Package URL or VERS comparison procedure.
    selector_purl = string(selector.get("purl"), "artifact selector purl")
    candidate_purl = string(candidate.get("purl"), "artifact purl")
    exact_purl = re.compile(r"^pkg:[a-z0-9.+-]+/[^@?#]+@[^@?#]+$")
    if selector.get("versionRange") is not None or not exact_purl.fullmatch(selector_purl):
        return "indeterminate"
    if selector_purl != candidate_purl:
        return "not-matched"

    candidate_digests: dict[tuple[Any, Any, Any], Any] = {}
    for raw_candidate in array(candidate.get("digests"), "artifact.digests"):
        digest = object_(raw_candidate, "artifact digest")
        key = (digest.get("algorithm"), digest.get("coverage"), digest.get("canonicalization"))
        if key in candidate_digests and candidate_digests[key] != digest.get("value"):
            fail("invalid", "conflicting-artifact-digests", "candidate has conflicting digests for one coverage")
        candidate_digests[key] = digest.get("value")

    required_coverages: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    for raw_digest in array(selector.get("digests", []), "artifact selector digests"):
        digest = object_(raw_digest, "artifact selector digest")
        coverage_key = (digest.get("coverage"), digest.get("canonicalization"))
        required_coverages.setdefault(coverage_key, []).append(digest)
    for (coverage, canonicalization), required in required_coverages.items():
        comparable = [
            digest for digest in required
            if (digest.get("algorithm"), coverage, canonicalization) in candidate_digests
        ]
        if not comparable:
            return "indeterminate"
        for digest in comparable:
            key = (digest.get("algorithm"), coverage, canonicalization)
            if candidate_digests[key] != digest.get("value"):
                return "not-matched"
    return "matched"


def applicability(model: dict[str, Any], candidate: dict[str, Any]) -> None:
    outcomes: list[str] = []
    for raw_selector in array(model.get("artifactSelectors"), "semanticModel.artifactSelectors"):
        selector = object_(raw_selector, "artifact selector")
        outcomes.append(selector_outcome(selector, candidate))
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


def provenance_resolver(document: dict[str, Any]):
    records = array(document.get("provenanceRecords"), "provenanceRecords")
    ids = [string(object_(record, "provenance record").get("id"), "provenance record id") for record in records]
    if len(ids) != len(set(ids)):
        fail("invalid", "duplicate-provenance", "provenance record ids must be unique")
    default = string(document.get("defaultProvenance"), "defaultProvenance")
    if default not in ids:
        fail("invalid", "missing-default-provenance", "default provenance does not resolve")

    def resolve(record: dict[str, Any]) -> list[str]:
        references = record.get("provenance", [default])
        values = [string(value, "provenance reference") for value in array(references, "provenance references")]
        if any(value not in ids for value in values):
            fail("invalid", "unresolved-provenance", "semantic fact has an unresolved provenance reference")
        return values

    return default, records, resolve


def descriptor_path(symbol: dict[str, Any], terminal_role: str) -> tuple[list[str], dict[str, Any]]:
    descriptors = array(symbol.get("descriptors"), "symbol.descriptors")
    if not descriptors:
        fail("invalid", "empty-symbol-descriptors", "symbol descriptors must not be empty")
    terminal = object_(descriptors[-1], "terminal symbol descriptor")
    if terminal.get("role") != terminal_role:
        fail("unsupported", "unsupported-symbol-shape", f"symbol must end in a {terminal_role} descriptor")
    prefix: list[str] = []
    prefix_roles: list[str] = []
    for raw_descriptor in descriptors[:-1]:
        descriptor = object_(raw_descriptor, "symbol descriptor")
        if descriptor.get("role") not in ("namespace", "type"):
            fail("unsupported", "unsupported-symbol-shape", "symbol owner contains an unsupported descriptor role")
        prefix_roles.append(descriptor["role"])
        prefix.append(string(descriptor.get("name"), "symbol descriptor name"))
    expected_roles = ["namespace"] * len(prefix_roles) if terminal_role == "type" else ["namespace"] * (len(prefix_roles) - 1) + ["type"]
    if not prefix_roles or prefix_roles != expected_roles:
        fail("unsupported", "unsupported-symbol-shape", "JVM symbol must contain namespaces followed by exactly one type")
    return prefix, terminal


def type_name(symbols: dict[str, dict[str, Any]], reference: Any, scheme: tuple[Any, Any]) -> str:
    reference = object_(reference, "type reference")
    if reference.get("kind") != "reference":
        fail("unsupported", "unsupported-type-reference", "Joern identity requires nominal reference types")
    symbol_id = string(reference.get("symbol"), "type reference symbol")
    symbol = symbols.get(symbol_id)
    if symbol is None:
        fail("invalid", "unresolved-type-reference", f"unresolved type symbol: {symbol_id}")
    if (symbol.get("scheme"), symbol.get("schemeVersion")) != scheme:
        fail("invalid", "type-scheme-mismatch", "callable and referenced type use different identity schemes")
    prefix, terminal = descriptor_path(symbol, "type")
    return ".".join(prefix + [string(terminal.get("name"), "type descriptor name")])


def joern_identity(
    model: dict[str, Any],
    symbol: dict[str, Any],
    declaration: dict[str, Any],
    symbols: dict[str, dict[str, Any]],
    candidate: dict[str, Any],
    methods: list[Any],
) -> dict[str, Any]:
    check_symbol_scope(model, symbol, candidate)
    scheme = (symbol.get("scheme"), symbol.get("schemeVersion"))
    if scheme not in SUPPORTED_SYMBOL_SCHEMES:
        fail("unsupported", "unsupported-symbol-scheme", f"unsupported callable symbol scheme {scheme[0]} {scheme[1]}")
    owner_id = string(declaration.get("owner"), "callable declaration owner")
    owner = symbols.get(owner_id)
    if owner is None:
        fail("invalid", "unresolved-callable-owner", f"unresolved callable owner: {owner_id}")
    owner_prefix, owner_terminal = descriptor_path(owner, "type")
    if (owner.get("scheme"), owner.get("schemeVersion")) != scheme:
        fail("invalid", "callable-owner-scheme-mismatch", "callable and owner use different identity schemes")
    owner_name = ".".join(owner_prefix + [string(owner_terminal.get("name"), "owner type name")])
    callable_prefix, callable_terminal = descriptor_path(symbol, "callable")
    if callable_prefix != owner_prefix + [string(owner_terminal.get("name"), "owner type name")]:
        fail("invalid", "callable-owner-mismatch", "callable descriptor path does not match its declared owner")
    shape = callable_shape(declaration)
    parameters = [type_name(symbols, item.get("type"), scheme) for item in shape["parameters"]]
    results = [type_name(symbols, item.get("type"), scheme) for item in shape["results"]]
    if len(results) != 1:
        fail("unsupported", "unsupported-result-shape", "Joern identity requires exactly one normal result")
    method_name = string(callable_terminal.get("name"), "callable descriptor name")
    signature = f"{results[0]}({','.join(parameters)})"
    expected_disambiguator = f"({','.join(parameters)})->{results[0]}"
    if callable_terminal.get("disambiguator") != expected_disambiguator:
        fail("invalid", "callable-disambiguator-mismatch", "callable disambiguator does not match its declaration")
    full_name = f"{owner_name}.{method_name}:{signature}"
    matches = [
        method for method in methods
        if isinstance(method, dict)
        and method.get("name") == method_name
        and method.get("signature") == signature
        and method.get("fullName") == full_name
    ]
    if len(matches) != 1:
        code = "unresolved-method-identity" if not matches else "ambiguous-method-identity"
        fail("incomplete", code, f"expected exactly one Joern METHOD for {full_name}, found {len(matches)}")
    method = matches[0]
    if method.get("isExternal") is not True:
        fail("inapplicable", "method-not-external", f"resolved Joern METHOD {full_name} is not external")
    string(method.get("fullName"), "resolved Joern method fullName")
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
    if location.get("projection") is not None:
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
        if phase == "output":
            fail("unsupported", "unsupported-parameter-writeback", "unprojected output parameters require a writeback vocabulary")
        return position + 1
    if phase == "output" and role == "result":
        position = root.get("position")
        if position != 0 or len(shape["results"]) != 1:
            fail("unsupported", "unsupported-result-shape", "Joern FlowSemantic projection requires exactly result[0]")
        return -1
    fail("unsupported", "unsupported-boundary-root", f"unsupported {phase} boundary role: {role!r}")


def complete_summary_symbols(model: dict[str, Any]) -> dict[str, dict[str, Any]]:
    complete: dict[str, dict[str, Any]] = {}
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
            complete[callable_id] = statement
        elif status in ("partial", "unknown"):
            fail("incomplete", f"{status}-procedure-summary", f"procedure summary coverage for {callable_id} is {status}")
        else:
            fail("unsupported", "unsupported-coverage-status", f"unsupported completeness status: {status!r}")
    return complete


def method_shape_matches(shape: dict[str, Any], method: dict[str, Any]) -> None:
    expected_receiver = isinstance(shape.get("receiver"), dict)
    # Joern reserves argument slot 0 for a Java static call's type qualifier as
    # well as for an instance receiver. CSMI's receiver is semantic, so an
    # absent CSMI receiver must not be contradicted by that syntactic Joern
    # slot. A declared CSMI receiver does require the slot to exist.
    if expected_receiver and method.get("hasReceiver") is not True:
        fail("incomplete", "receiver-shape-mismatch", "Joern lacks the receiver slot required by CSMI")
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
    default_provenance, provenance_records, resolve_provenance = provenance_resolver(document)
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
        shape = callable_shape(declaration)
        method = joern_identity(model, symbol, declaration, symbols, artifact, methods)
        full_name = string(method.get("fullName"), "resolved Joern method fullName")
        method_shape_matches(shape, method)
        # Joern 4.0.592 requires input self-mappings to mark call arguments as
        # used/defined; without them an empty FlowSemantic still permits
        # argument-to-argument overpropagation. These operational identities do
        # not represent CSMI cross-boundary transfers.
        self_mappings: set[tuple[int, int]] = {(0, 0)}
        self_mappings.update((position + 1, position + 1) for position in range(len(shape["parameters"])))
        transfer_mappings: set[tuple[int, int]] = set()
        for raw_transfer in array(summary.get("transfers"), "procedureSummary.transfers"):
            transfer = object_(raw_transfer, "transfer")
            source = slot(object_(transfer.get("source"), "transfer.source"), shape, "input")
            destination = slot(object_(transfer.get("destination"), "transfer.destination"), shape, "output")
            transfer_mappings.add((source, destination))
        coverage = complete[callable_id]
        output.append({
            "methodFullName": full_name,
            "regex": False,
            "mappings": [list(item) for item in sorted(self_mappings | transfer_mappings)],
            "csmiTransferMappings": [list(item) for item in sorted(transfer_mappings)],
            "joernInputSelfMappings": [list(item) for item in sorted(self_mappings)],
            "summaryProvenance": resolve_provenance(summary),
            "coverage": {
                "family": "procedure-summaries",
                "status": "complete",
                "provenance": resolve_provenance(coverage),
            },
        })

    missing = set(complete) - seen
    if missing:
        fail("invalid", "complete-summary-missing", f"complete summary scopes lack summaries: {sorted(missing)}")
    if not output:
        fail("incomplete", "no-projected-summaries", "no complete Joern-projectable procedure summaries were present")
    return {
        "schemaVersion": 1,
        "outcome": "applied",
        "joern": {"version": JOERN_IDENTITY_VERSION, "identityScheme": JOERN_IDENTITY_SCHEME},
        "csmi": {
            "packDigest": loaded.digest,
            "semanticDocumentDigest": loaded.document_digest,
            "defaultProvenance": default_provenance,
            "provenanceRecords": provenance_records,
        },
        "semantics": output,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--methods", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result: dict[str, Any]
    exit_code = 0
    try:
        loaded, artifact = load_scenario_pack(args.scenario)
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
