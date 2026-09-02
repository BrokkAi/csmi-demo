#!/usr/bin/env python3
"""Small, dependency-free consumer for the CSMI Rust 0.1 profile.

This is intentionally an independent semantic projection: local fixture IDs are
used only as references, while every reported meaning is derived from the
resolver-shaped source-item key and profile facts.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CSMI_SCHEMA = "https://csmi.brokk.ai/schema/0.1/schema.json"
PROFILE = "csmi.rust"
PROFILE_VERSION = "0.1.0"
PROFILE_SCHEMA = "https://csmi.brokk.ai/schema/profiles/rust/0.1/schema.json"
SOURCE_SCHEME = "csmi.rust.source-item"
SOURCE_SCHEME_VERSION = "0.1.0"
EXPECTED_PURL = "pkg:cargo/acme-codec@1.4.0"
ROOT_RE = re.compile(r"^(lib|bin|example|test|bench|proc-macro|build-script):")
HEX256_RE = re.compile(r"^[0-9a-f]{64}$")


class ConsumerFailure(ValueError):
    """A typed fail-closed result; never silently returns an empty model."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ConsumerFailure(code, message)


def obj(value: Any, context: str) -> Dict[str, Any]:
    require(isinstance(value, dict), "malformed-model", f"{context} must be an object")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerFailure("malformed-model", f"cannot read semantic document: {exc}") from exc
    return obj(value, "semantic document")


def identity(symbol: Dict[str, Any], selectors: List[Any]) -> Dict[str, Any]:
    return {
        "artifactSelectors": copy.deepcopy(symbol.get("artifactSelectors", selectors)),
        "scheme": symbol["scheme"],
        "schemeVersion": symbol["schemeVersion"],
        "stability": symbol["stability"],
        "descriptors": copy.deepcopy(symbol["descriptors"]),
    }


def find_unique(symbols: Iterable[Dict[str, Any]], predicate: Any, label: str) -> Dict[str, Any]:
    matches = [symbol for symbol in symbols if predicate(symbol)]
    require(len(matches) == 1, "ambiguous-or-missing-identity", f"expected one {label}, got {len(matches)}")
    return matches[0]


def path(symbol: Dict[str, Any]) -> List[tuple[str, str, str]]:
    return [(d["role"], d["name"], d["disambiguator"]) for d in symbol["descriptors"]]


def fact(model: Dict[str, Any], family: str) -> Dict[str, Any]:
    matches = [
        obj(item, f"{family} fact")
        for item in model.get("extensionFacts", [])
        if isinstance(item, dict) and item.get("vocabulary") == PROFILE and item.get("version") == PROFILE_VERSION and item.get("family") == family
    ]
    require(len(matches) == 1, "missing-or-ambiguous-fact", f"expected one {family} fact")
    return obj(matches[0].get("payload"), f"{family} payload")


def complete(model: Dict[str, Any], family: str, scope: Dict[str, Any], vocabulary: bool = True) -> None:
    matches = []
    for raw in model.get("completenessStatements", []):
        statement = obj(raw, "completeness statement")
        if statement.get("family") == family and statement.get("scope") == scope and (not vocabulary or statement.get("vocabulary") == PROFILE):
            matches.append(statement)
    require(len(matches) == 1 and matches[0].get("status") == "complete", "incomplete-coverage", f"{family} coverage is not complete for its exact scope")


def project(document: Dict[str, Any], candidate_config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    require(document.get("documentType") == "semantic-document", "malformed-model", "unsupported document type")
    require(document.get("schema") == CSMI_SCHEMA and document.get("semanticModelVersion") == "0.1" and document.get("serializationVersion") == "0.1-json", "unsupported-core", "unsupported CSMI core version")
    models = document.get("semanticModels")
    require(isinstance(models, list) and len(models) == 1, "unsupported-model-shape", "this consumer requires exactly one semantic model")
    model = obj(models[0], "semantic model")

    uses = [obj(use, "vocabulary use") for use in model.get("vocabularyUses", []) if isinstance(use, dict)]
    rust_uses = [use for use in uses if use.get("identifier") == PROFILE]
    require(len(rust_uses) == 1 and rust_uses[0].get("version") == PROFILE_VERSION and rust_uses[0].get("schema") == PROFILE_SCHEMA and rust_uses[0].get("requirement") == "required", "unsupported-required-profile", "csmi.rust 0.1.0 is required and unsupported otherwise")

    selectors = model.get("artifactSelectors")
    require(isinstance(selectors, list) and len(selectors) == 1, "unsupported-applicability", "one exact Cargo artifact selector is required")
    selector = obj(selectors[0], "artifact selector")
    require(selector.get("purl") == EXPECTED_PURL and "versionRange" not in selector, "artifact-not-matched", "the exact Cargo package is not selected")

    config_constraints = [obj(item, "compatibility constraint") for item in model.get("compatibilityConstraints", []) if isinstance(item, dict) and item.get("vocabulary") == PROFILE]
    require(len(config_constraints) == 1 and config_constraints[0].get("version") == PROFILE_VERSION, "configuration-indeterminate", "one csmi.rust configuration is required")
    config = obj(config_constraints[0].get("value"), "Rust configuration")
    expected_config = candidate_config or config
    required_config = ("kind", "edition", "compiler", "cargoResolver", "target", "compilationRole", "enabledFeatures", "cfgAtoms")
    require(all(key in expected_config for key in required_config), "configuration-indeterminate", "candidate Rust configuration is incomplete")
    for key in required_config:
        require(config.get(key) == expected_config.get(key), "configuration-incompatible", f"Rust configuration differs at {key}")

    raw_symbols = model.get("symbols")
    require(isinstance(raw_symbols, list) and raw_symbols, "malformed-model", "symbols must be non-empty")
    symbols: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for raw in raw_symbols:
        symbol = obj(raw, "symbol")
        sid = symbol.get("id")
        require(isinstance(sid, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", sid) and sid not in by_id, "malformed-model", "symbol IDs must be unique local handles")
        require(symbol.get("scheme") == SOURCE_SCHEME and symbol.get("schemeVersion") == SOURCE_SCHEME_VERSION, "unsupported-symbol-scheme", "Rust source identity scheme is unsupported")
        descriptors = symbol.get("descriptors")
        require(isinstance(descriptors, list) and descriptors, "invalid-source-identity", "source-item identity has no descriptors")
        roots = [d for d in descriptors if isinstance(d, dict) and ROOT_RE.match(str(d.get("disambiguator", "")))]
        require(len(roots) == 1 and roots[0] is descriptors[0] and descriptors[0].get("role") == "namespace" and descriptors[0].get("name") == "crate", "invalid-source-identity", "identity must begin with exactly one Cargo-resolved crate root")
        for descriptor in descriptors:
            descriptor = obj(descriptor, "source descriptor")
            require(set(descriptor) == {"role", "name", "disambiguator"}, "invalid-source-identity", "source descriptors are closed objects")
            require(isinstance(descriptor["name"], str) and descriptor["name"] == unicodedata.normalize("NFC", descriptor["name"]) and not descriptor["name"].startswith("r#"), "invalid-source-identity", "descriptor names must be normalized resolver identifiers")
        require(symbol.get("stability") in ("portable", "artifact-local"), "invalid-source-identity", "unknown source-item stability")
        if symbol.get("stability") == "artifact-local":
            require(all("digests" in obj(item, "artifact selector") for item in selectors), "invalid-source-identity", "artifact-local identity requires exact selector digests")
        by_id[sid] = symbol
        symbols.append(symbol)

    declarations: Dict[str, Dict[str, Any]] = {}
    for raw in model.get("declarations", []):
        declaration = obj(raw, "declaration")
        sid = declaration.get("symbol")
        require(sid in by_id and sid not in declarations, "invalid-declaration", "declaration references a missing or duplicate symbol")
        if "owner" in declaration:
            require(declaration["owner"] in by_id, "invalid-declaration", "declaration owner is unresolved")
        declarations[sid] = declaration

    rust_symbols = list(symbols)
    root = find_unique(rust_symbols, lambda s: len(s["descriptors"]) == 1, "crate root")
    root_id = root["id"]
    crate_payload = fact(model, "crate-mappings")
    require(crate_payload.get("kind") == "crate-target" and crate_payload.get("packagePurl") == EXPECTED_PURL and crate_payload.get("targetKind") == "lib" and crate_payload.get("targetName") == "acme-codec" and crate_payload.get("crateName") == "acme_codec" and crate_payload.get("compilationRole") == "target", "invalid-crate-mapping", "crate target mapping is not resolver-proven")
    require(root["descriptors"][0]["disambiguator"] == "lib:acme_codec", "invalid-crate-mapping", "crate root must come from the resolved target crate, not package-name spelling")

    def exact_path(expected: List[tuple[str, str, str]], label: str) -> Dict[str, Any]:
        return find_unique(rust_symbols, lambda s: path(s) == expected, label)

    root_descriptor = ("namespace", "crate", "lib:acme_codec")
    format_module = exact_path([root_descriptor, ("namespace", "format", "module")], "format module")
    display_trait = exact_path([root_descriptor, ("namespace", "format", "module"), ("type", "Display", "trait")], "Display trait")
    display_method = exact_path(path(display_trait) + [("callable", "display", "method")], "trait display method")
    record_type = exact_path([root_descriptor, ("type", "Record", "struct")], "Record type")
    record_parse = exact_path(path(record_type) + [("callable", "parse", "associated-function")], "inherent associated function")
    record_parse_t = exact_path(path(record_parse) + [("type-parameter", "0", "type-parameter")], "generic type parameter")
    display_impl = find_unique(rust_symbols, lambda s: len(s["descriptors"]) == 2 and s["descriptors"][1]["role"] == "meta" and s["descriptors"][1]["name"] == "impl" and s["descriptors"][1]["disambiguator"].startswith("jcs-sha256:"), "trait implementation")
    record_display = exact_path(path(display_impl) + [("callable", "display", "method")], "provided trait method")
    derive_parser = exact_path([root_descriptor, ("meta", "Parser", "proc-macro-derive")], "derive macro")
    generated_parser = exact_path([root_descriptor, ("type", "GeneratedParser", "struct")], "generated item")
    require(generated_parser.get("origin") == "generated", "invalid-generation", "generated item lacks generated origin")

    def declared(sid: str, owner: Optional[str], category: str) -> Dict[str, Any]:
        declaration = declarations.get(sid)
        require(declaration is not None and declaration.get("category") == category and (owner is None or declaration.get("owner") == owner), "invalid-declaration", f"invalid declaration ownership for {sid}")
        return declaration

    declared(root_id, None, "namespace")
    declared(format_module["id"], root_id, "namespace")
    declared(display_trait["id"], format_module["id"], "type")
    parse_decl = declared(record_parse["id"], record_type["id"], "callable")
    generic_decl = declared(record_parse_t["id"], record_parse["id"], "type-parameter")
    require(parse_decl.get("genericParameters") == [{"position": 0, "symbol": record_parse_t["id"], "kind": "type"}] and generic_decl.get("owner") == record_parse["id"], "invalid-generic-binding", "generic declaration is not resolver-owned by the inherent function")
    callable_shape = obj(parse_decl.get("callable"), "record parse callable")
    require(callable_shape.get("kind") == "function" and "receiver" not in callable_shape, "invalid-inherent-function", "associated function must not gain a receiver")
    declared(display_method["id"], display_trait["id"], "callable")
    declared(display_impl["id"], root_id, "meta")
    declared(record_display["id"], display_impl["id"], "callable")

    reexport = fact(model, "reexports")
    require(reexport == {"kind": "reexport", "exportingModule": root_id, "exportedName": "Display", "namespace": "type", "target": display_trait["id"]}, "invalid-reexport", "reexport is not bound to the exact resolved target")
    impl = fact(model, "implementations")
    require(impl.get("kind") == "implementation" and impl.get("implementation") == display_impl["id"] and impl.get("implementingType") == record_type["id"] and impl.get("trait") == display_trait["id"], "invalid-implementation", "trait implementation ownership is unresolved")
    key = impl.get("identityKey")
    require(isinstance(key, dict) and key.get("trait") == identity(display_trait, selectors), "invalid-implementation", "implementation trait key is not the exact source identity")
    type_pattern = obj(key.get("implementingType"), "implementation self type")
    require(type_pattern.get("kind") == "declared" and type_pattern.get("symbol") == identity(record_type, selectors) and key.get("binders") == [], "invalid-implementation", "implementation self type is not the exact declared type")
    require(display_impl["descriptors"][-1]["disambiguator"] == "jcs-sha256:" + hashlib.sha256(canonical(key)).hexdigest(), "invalid-implementation", "implementation identity digest does not cover its structured key")
    require(impl.get("associatedItems") == [{"providedItem": record_display["id"], "traitItem": display_method["id"]}], "invalid-associated-item", "trait item correspondence must be structural, not name-only")
    relationships = model.get("relationships", [])
    require(any(isinstance(r, dict) and r.get("subject") == record_display["id"] and r.get("predicate") == "implements" and r.get("object") == display_method["id"] for r in relationships), "invalid-relationship", "missing exact implements relationship")

    generation = fact(model, "generation")
    require(generation == {"kind": "generation", "item": generated_parser["id"], "generatorKind": "procedural-macro", "generator": derive_parser["id"], "portability": "portable", "generatorArtifactSha256": generation.get("generatorArtifactSha256"), "inputSha256": generation.get("inputSha256"), "outputSha256": generation.get("outputSha256")}, "invalid-generation", "generation fact is not tied to the resolved generated item")
    for key_name in ("generatorArtifactSha256", "inputSha256", "outputSha256"):
        require(isinstance(generation.get(key_name), str) and HEX256_RE.fullmatch(generation[key_name]) is not None, "invalid-generation", "portable generation requires exact evidence digests")

    native = fact(model, "native-mappings")
    require(native.get("kind") == "native-mapping" and native.get("source") == record_parse["id"] and native.get("status") == "exact" and native.get("cardinality") == "one-to-one" and isinstance(native.get("nativeIdentities"), list) and native["nativeIdentities"], "invalid-native-boundary", "native mapping is not explicit exact evidence")
    require(HEX256_RE.fullmatch(str(native.get("artifactSha256"))) is not None and native.get("compilerRelease") == config["compiler"]["release"] and native.get("targetTriple") == config["target"]["triple"], "invalid-native-boundary", "native mapping lacks exact artifact/toolchain scope")

    summary = [item for item in model.get("procedureSummaries", []) if isinstance(item, dict) and item.get("callable") == record_parse["id"]]
    require(len(summary) == 1 and len(summary[0].get("transfers", [])) == 1, "invalid-summary", "inherent function summary is missing or ambiguous")
    transfer = summary[0]["transfers"][0]
    require(transfer == {"source": {"root": {"phase": "input", "role": "parameter", "position": 0}}, "destination": {"root": {"phase": "output", "role": "result", "position": 0}}}, "invalid-summary", "summary boundary is not an exact parameter-to-result transfer")
    complete(model, "procedure-summaries", {"callable": record_parse["id"]}, vocabulary=False)
    complete(model, "reexports", {"exportingModule": root_id, "namespace": "type"})
    complete(model, "generation", {"symbol": generated_parser["id"]})

    return {
        "resultFormatVersion": "csmi-demo-rust-profile-result/1",
        "status": "complete",
        "profile": {"identifier": PROFILE, "version": PROFILE_VERSION, "scheme": SOURCE_SCHEME, "schemeVersion": SOURCE_SCHEME_VERSION},
        "artifact": {"purl": EXPECTED_PURL},
        "meanings": {
            "crateRoot": identity(root, selectors),
            "inherentAssociatedFunction": {"identity": identity(record_parse, selectors), "owner": identity(record_type, selectors), "genericParameter": identity(record_parse_t, selectors)},
            "traitImplementation": {"identity": identity(display_impl, selectors), "implementingType": identity(record_type, selectors), "trait": identity(display_trait, selectors), "providedItem": identity(record_display, selectors), "traitItem": identity(display_method, selectors)},
            "generation": {"item": identity(generated_parser, selectors), "generator": identity(derive_parser, selectors), "portability": generation["portability"], "outputSha256": generation["outputSha256"]},
            "nativeBoundary": {"source": identity(record_parse, selectors), "status": native["status"], "cardinality": native["cardinality"], "nativeSystem": native["nativeSystem"], "nativeVersion": native["nativeVersion"], "nativeIdentities": native["nativeIdentities"], "artifactSha256": native["artifactSha256"]},
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", type=Path, default=Path(__file__).parent / "fixtures" / "rust-profile.json")
    args = parser.parse_args(argv)
    try:
        result = project(load(args.document))
    except ConsumerFailure as exc:
        print(json.dumps({"status": "failed", "failure": {"code": exc.code, "message": exc.message}}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
