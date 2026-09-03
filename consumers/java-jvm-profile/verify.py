#!/usr/bin/env python3
"""Independent, dependency-free consumer for the CSMI Java/JVM profiles.

The fixture deliberately keeps Java source identity and JVM binary identity in
different schemes.  This consumer resolves both structurally, then accepts a
source-to-binary relation only when the mapping fact and its build evidence
name those exact local records.  Compatibility is evaluated against explicit
candidate runtime/class-file evidence supplied by the caller; constraints are
never treated as that evidence.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import urlparse


CSMI_SCHEMA = "https://csmi.brokk.ai/schema/0.1/schema.json"
CORE_VERSION = "0.1"
SERIALIZATION_VERSION = "0.1-json"
MAVEN_PURL = "pkg:maven/org.example/normalize@1.4.2?type=jar"
SOURCE_PURL = "pkg:maven/org.example/normalize@1.4.2?classifier=sources&type=jar"

SOURCE_PROFILE = "csmi.java-source-identity"
BINARY_PROFILE = "csmi.jvm-binary-identity"
MAPPING_PROFILE = "csmi.java-jvm-mapping"
COMPATIBILITY_PROFILE = "csmi.jvm-compatibility"
PROFILE_VERSION = "0.1"
SOURCE_SCHEMA = "https://csmi.brokk.ai/schema/profiles/java-jvm/0.1/java-source-identity.schema.json"
BINARY_SCHEMA = "https://csmi.brokk.ai/schema/profiles/java-jvm/0.1/jvm-binary-identity.schema.json"
MAPPING_SCHEMA = "https://csmi.brokk.ai/schema/profiles/java-jvm/0.1/java-jvm-mapping.schema.json"
COMPATIBILITY_SCHEMA = "https://csmi.brokk.ai/schema/profiles/java-jvm/0.1/jvm-compatibility.schema.json"

LOCAL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
HEX256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER_RE = re.compile(r"^[^\s./;\[\]<>:]+$")
INTERNAL_NAME_RE = re.compile(r"^[^.;\[/]+(?:/[^.;\[/]+)*$")

EXPECTED_USES = {
    SOURCE_PROFILE: SOURCE_SCHEMA,
    BINARY_PROFILE: BINARY_SCHEMA,
    MAPPING_PROFILE: MAPPING_SCHEMA,
    COMPATIBILITY_PROFILE: COMPATIBILITY_SCHEMA,
}
EXPECTED_AFFECTS = {
    SOURCE_PROFILE: [
        {
            "kind": "core-slot",
            "slot": "symbol.identity-scheme",
            "target": {"symbol": "java-normalize"},
        }
    ],
    BINARY_PROFILE: [
        {
            "kind": "core-slot",
            "slot": "symbol.identity-scheme",
            "target": {"symbol": "jvm-normalize"},
        }
    ],
    MAPPING_PROFILE: [
        {
            "kind": "fact-family",
            "family": "java-jvm-mapping",
            "scope": {"sourceSymbol": "java-normalize"},
        }
    ],
    COMPATIBILITY_PROFILE: [
        {
            "kind": "core-slot",
            "slot": "semantic-model.compatibility",
            "target": {"artifactSelectors": "model"},
        }
    ],
}
SUPPORTED_CONSTRAINTS = {
    "javaRelease",
    "classFileMajor",
    "targetPlatform",
    "jdkModule",
    "jvmVendor",
    "kotlinMetadataVersion",
    "scalaBinaryVersion",
    "multiReleaseSelection",
}
EVIDENCE_KINDS = {
    "compiler-symbol-table",
    "classfile-metadata",
    "language-metadata",
    "verified-build-output",
}
MAPPING_KINDS = {"direct", "erased", "bridge", "lowered", "generated", "relocated"}


class ConsumerFailure(ValueError):
    """A typed fail-closed result; an empty projection is never success."""

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
    """The fixture's JSON values are JCS-compatible with this canonical form."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def local_id(value: Any, context: str) -> str:
    require(isinstance(value, str) and LOCAL_ID_RE.fullmatch(value) is not None, "malformed-model", f"{context} is not a valid local handle")
    return value


def digest(value: Any, context: str) -> str:
    require(isinstance(value, str) and HEX256_RE.fullmatch(value) is not None, "invalid-evidence", f"{context} must be a lowercase SHA-256 digest")
    return value


def uri(value: Any, context: str) -> str:
    require(isinstance(value, str), "invalid-evidence", f"{context} must be an absolute URI")
    parsed = urlparse(value)
    require(bool(parsed.scheme) and bool(value), "invalid-evidence", f"{context} must be an absolute URI")
    return value


def load(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerFailure("malformed-model", f"cannot read semantic document: {exc}") from exc
    return obj(value, "semantic document")


def find_unique(items: Iterable[Dict[str, Any]], predicate: Any, label: str) -> Dict[str, Any]:
    matches = [item for item in items if predicate(item)]
    require(len(matches) == 1, "ambiguous-or-missing-identity", f"expected one {label}, got {len(matches)}")
    return matches[0]


def validate_selector(selector: Any, expected_purl: str, expected_coverage: str, context: str) -> Dict[str, Any]:
    value = obj(selector, context)
    require(value.get("purl") == expected_purl and "versionRange" not in value, "artifact-not-matched", f"{context} is not the exact selected Maven artifact")
    digests = value.get("digests")
    require(isinstance(digests, list) and len(digests) == 1, "incomplete-artifact-evidence", f"{context} requires one exact digest")
    item = obj(digests[0], f"{context} digest")
    require(item.get("algorithm") == "sha-256" and item.get("coverage") == expected_coverage, "incomplete-artifact-evidence", f"{context} digest has the wrong algorithm or coverage")
    digest(item.get("value"), f"{context} digest value")
    return value


def validate_uses(model: Dict[str, Any]) -> None:
    raw_uses = model.get("vocabularyUses")
    require(isinstance(raw_uses, list), "missing-vocabulary-use", "vocabularyUses must be present")
    uses = [obj(item, "vocabulary use") for item in raw_uses]
    by_identifier: Dict[str, List[Dict[str, Any]]] = {}
    for use in uses:
        identifier = use.get("identifier")
        require(isinstance(identifier, str), "malformed-model", "vocabulary identifier must be a string")
        by_identifier.setdefault(identifier, []).append(use)
        if use.get("requirement") == "required" and (
            identifier not in EXPECTED_USES
            or use.get("version") != PROFILE_VERSION
            or use.get("schema") != EXPECTED_USES.get(identifier)
        ):
            raise ConsumerFailure("unsupported-required-profile", f"required vocabulary {identifier!r} is unsupported at this version")
    for identifier, schema in EXPECTED_USES.items():
        matches = by_identifier.get(identifier, [])
        require(len(matches) == 1, "missing-vocabulary-use", f"exact required vocabulary use {identifier} is missing or ambiguous")
        use = matches[0]
        require(use.get("version") == PROFILE_VERSION and use.get("schema") == schema and use.get("requirement") == "required", "unsupported-required-profile", f"{identifier} 0.1 is required with its exact schema")
        require(use.get("affects") == EXPECTED_AFFECTS[identifier], "invalid-vocabulary-scope", f"{identifier} does not declare the exact affected unit")


def validate_provenance(document: Dict[str, Any]) -> None:
    records = document.get("provenanceRecords")
    require(isinstance(records, list) and records, "incomplete-provenance", "provenance records are required")
    ids = {local_id(obj(record, "provenance record").get("id"), "provenance record ID") for record in records}
    default = document.get("defaultProvenance")
    require(isinstance(default, str) and default in ids, "incomplete-provenance", "default provenance does not resolve")


def parse_canonical_json(value: Any, context: str) -> Dict[str, Any]:
    require(isinstance(value, str), "invalid-source-identity", f"{context} must be a canonical JSON signature")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConsumerFailure("invalid-source-identity", f"{context} is not JSON") from exc
    require(isinstance(parsed, dict) and canonical(parsed).decode("utf-8") == value, "invalid-source-identity", f"{context} is not canonical JCS")
    return parsed


def validate_source_symbol(symbol: Dict[str, Any], source_selectors: List[Dict[str, Any]]) -> Dict[str, Any]:
    require(symbol.get("scheme") == SOURCE_PROFILE and symbol.get("schemeVersion") == PROFILE_VERSION, "unsupported-source-profile", "source symbol uses an unsupported identity scheme")
    require(symbol.get("stability") == "portable", "invalid-source-identity", "Java source identity must be portable for this consumer")
    selectors = symbol.get("artifactSelectors")
    require(isinstance(selectors, list) and len(selectors) == 1, "incomplete-artifact-evidence", "source identity requires one exact sources artifact selector")
    require(validate_selector(selectors[0], SOURCE_PURL, "source-archive", "source artifact selector") == selectors[0], "invalid-source-identity", "source selector changed during validation")
    require(selectors == source_selectors, "invalid-source-identity", "source artifact scope is not the exact selected source archive")
    descriptors = symbol.get("descriptors")
    require(isinstance(descriptors, list) and len(descriptors) == 4, "invalid-source-identity", "expected package, owner, and callable source descriptors")
    expected_prefix = [("namespace", "org"), ("namespace", "example"), ("type", "Strings")]
    for descriptor, (role, name) in zip(descriptors[:3], expected_prefix):
        item = obj(descriptor, "Java source descriptor")
        require(set(item) <= {"role", "name", "disambiguator"} and item.get("role") == role and item.get("name") == name, "invalid-source-identity", "source identity is not the resolver-proven package/owner path")
        require(IDENTIFIER_RE.fullmatch(name) is not None, "invalid-source-identity", "source descriptor contains an invalid identifier")
        require("disambiguator" not in item, "invalid-source-identity", "package and owner descriptors must not use display disambiguators")
    callable_descriptor = obj(descriptors[3], "Java callable descriptor")
    require(set(callable_descriptor) == {"role", "name", "disambiguator"} and callable_descriptor.get("role") == "callable" and callable_descriptor.get("name") == "normalize", "invalid-source-identity", "source callable identity is not exact")
    signature = parse_canonical_json(callable_descriptor.get("disambiguator"), "Java callable signature")
    require(set(signature) <= {"receiverType", "parameterTypes", "genericArity"} and isinstance(signature.get("parameterTypes"), list) and len(signature["parameterTypes"]) == 1, "invalid-source-identity", "source callable signature is incomplete")
    parameter = obj(signature["parameterTypes"][0], "Java source parameter")
    require(set(parameter) <= {"canonicalName", "nullability", "parameterMode"} and parameter.get("canonicalName") == "java.lang.String" and parameter.get("nullability") == "unspecified" and parameter.get("parameterMode") == "value", "invalid-source-identity", "source parameter is not a resolver-proven java.lang.String value")
    return {
        "scheme": symbol["scheme"],
        "schemeVersion": symbol["schemeVersion"],
        "stability": symbol["stability"],
        "artifactSelectors": copy.deepcopy(selectors),
        "descriptors": copy.deepcopy(descriptors),
        "callableSignature": copy.deepcopy(signature),
    }


def parse_field_descriptor(value: str, start: int, allow_void: bool = False) -> int:
    position = start
    while position < len(value) and value[position] == "[":
        position += 1
    require(position < len(value), "invalid-binary-identity", "JVM descriptor ends after an array marker")
    kind = value[position]
    if kind == "L":
        end = value.find(";", position + 1)
        require(end > position + 1 and INTERNAL_NAME_RE.fullmatch(value[position + 1 : end]) is not None, "invalid-binary-identity", "JVM object descriptor has an invalid internal name")
        return end + 1
    allowed = "BCDFIJSZ" + ("V" if allow_void and position == start else "")
    require(kind in allowed, "invalid-binary-identity", "JVM descriptor contains an invalid field type")
    require(not (kind == "V" and position != start), "invalid-binary-identity", "void is not valid inside a JVM descriptor")
    return position + 1


def validate_method_descriptor(value: Any) -> str:
    require(isinstance(value, str) and value.startswith("("), "invalid-binary-identity", "JVM method descriptor is missing")
    position = 1
    while position < len(value) and value[position] != ")":
        position = parse_field_descriptor(value, position)
    require(position < len(value) and value[position] == ")", "invalid-binary-identity", "JVM method descriptor has no closing parameter delimiter")
    end = parse_field_descriptor(value, position + 1, allow_void=True)
    require(end == len(value), "invalid-binary-identity", "JVM method descriptor has trailing data")
    return value


def validate_binary_symbol(symbol: Dict[str, Any], binary_selectors: List[Dict[str, Any]]) -> Dict[str, Any]:
    require(symbol.get("scheme") == BINARY_PROFILE and symbol.get("schemeVersion") == PROFILE_VERSION, "unsupported-binary-profile", "binary symbol uses an unsupported identity scheme")
    require(symbol.get("stability") == "portable", "invalid-binary-identity", "JVM binary identity must be portable for this consumer")
    selectors = symbol.get("artifactSelectors")
    if selectors is not None:
        require(isinstance(selectors, list) and selectors == binary_selectors, "invalid-binary-identity", "binary identity has a non-selected artifact scope")
    descriptors = symbol.get("descriptors")
    require(isinstance(descriptors, list) and len(descriptors) == 4, "invalid-binary-identity", "expected package, owner, and callable binary descriptors")
    expected_prefix = [("namespace", "org"), ("namespace", "example"), ("type", "Strings")]
    for descriptor, (role, name) in zip(descriptors[:3], expected_prefix):
        item = obj(descriptor, "JVM binary descriptor")
        require(set(item) <= {"role", "name", "disambiguator"} and item.get("role") == role and item.get("name") == name, "invalid-binary-identity", "binary identity is not the exact owner path")
        require(IDENTIFIER_RE.fullmatch(name) is not None, "invalid-binary-identity", "binary descriptor contains an invalid identifier")
        require("disambiguator" not in item, "invalid-binary-identity", "package and owner descriptors must not use display disambiguators")
    callable_descriptor = obj(descriptors[3], "JVM method descriptor")
    require(set(callable_descriptor) == {"role", "name", "disambiguator"} and callable_descriptor.get("role") == "callable" and callable_descriptor.get("name") == "normalize", "invalid-binary-identity", "binary method identity is not exact")
    descriptor = validate_method_descriptor(callable_descriptor.get("disambiguator"))
    require(descriptor == "(Ljava/lang/String;)Ljava/lang/String;", "invalid-binary-identity", "binary descriptor does not exactly match the mapped method")
    return {
        "scheme": symbol["scheme"],
        "schemeVersion": symbol["schemeVersion"],
        "stability": symbol["stability"],
        "artifactSelectors": copy.deepcopy(binary_selectors),
        "owner": "org/example/Strings",
        "binaryEntity": {"kind": "method", "name": "normalize", "descriptor": descriptor},
        "variant": {"entryPath": "org/example/Strings.class", "release": 0},
        "descriptors": copy.deepcopy(descriptors),
    }


def validate_compatibility(model: Dict[str, Any], candidate: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    raw_constraints = model.get("compatibilityConstraints")
    require(isinstance(raw_constraints, list), "incomplete-compatibility-evidence", "compatibility constraints are required")
    matches = [
        obj(item, "compatibility constraint")
        for item in raw_constraints
        if isinstance(item, dict) and item.get("vocabulary") == COMPATIBILITY_PROFILE
    ]
    require(len(matches) == 1 and matches[0].get("version") == PROFILE_VERSION, "unsupported-required-profile", "one exact JVM compatibility constraint is required")
    value = obj(matches[0].get("value"), "JVM compatibility value")
    require(value.get("profileVersion") == PROFILE_VERSION, "unsupported-required-profile", "JVM compatibility payload version is unsupported")
    constraints = obj(value.get("constraints"), "JVM compatibility constraints")
    require(bool(constraints), "invalid-compatibility-constraints", "JVM compatibility constraints cannot be empty")
    for key, expected in constraints.items():
        require(key in SUPPORTED_CONSTRAINTS, "unsupported-compatibility-constraint", f"JVM compatibility constraint {key!r} is unsupported")
        if key in ("javaRelease", "classFileMajor"):
            interval = obj(expected, f"{key} range")
            require(set(interval) <= {"minimum", "maximum"} and bool(interval), "invalid-compatibility-constraints", f"{key} range is malformed")
            for bound in interval.values():
                require(isinstance(bound, int) and not isinstance(bound, bool) and bound >= 0, "invalid-compatibility-constraints", f"{key} bounds must be non-negative integers")
            require(not ("minimum" in interval and "maximum" in interval and interval["minimum"] > interval["maximum"]), "invalid-compatibility-constraints", f"{key} minimum exceeds maximum")
        elif key == "kotlinMetadataVersion":
            require(isinstance(expected, list) and 1 <= len(expected) <= 4 and all(isinstance(part, int) and not isinstance(part, bool) and part >= 0 for part in expected), "invalid-compatibility-constraints", "Kotlin metadata version is malformed")
        elif key == "multiReleaseSelection":
            require(isinstance(expected, int) and not isinstance(expected, bool) and expected >= 8, "invalid-compatibility-constraints", "multi-release selection must be a Java release")
        elif key == "targetPlatform":
            require(expected in ("jvm", "android"), "invalid-compatibility-constraints", "target platform is unsupported")
        elif key == "jdkModule":
            require(isinstance(expected, str) and expected and all(part for part in expected.split(".")), "invalid-compatibility-constraints", "JDK module evidence is malformed")
        elif key == "jvmVendor":
            uri(expected, "JVM vendor")
        elif key == "scalaBinaryVersion":
            require(isinstance(expected, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", expected) is not None, "invalid-compatibility-constraints", "Scala binary version is malformed")

    supplied = dict(candidate or {})
    required_candidate = {"javaRelease", "classFileMajor", "targetPlatform"} | set(constraints)
    missing = sorted(required_candidate - set(supplied))
    require(not missing, "incomplete-compatibility-evidence", f"candidate compatibility evidence is missing: {', '.join(missing)}")
    for key in required_candidate:
        actual = supplied[key]
        expected = constraints.get(key)
        if key in ("javaRelease", "classFileMajor"):
            require(isinstance(actual, int) and not isinstance(actual, bool) and actual >= 0, "incomplete-compatibility-evidence", f"candidate {key} is not an integer")
            if expected is not None:
                if "minimum" in expected and actual < expected["minimum"] or "maximum" in expected and actual > expected["maximum"]:
                    raise ConsumerFailure("incompatible-constraints", f"candidate {key} does not satisfy its inclusive range")
        elif key == "targetPlatform":
            require(actual in ("jvm", "android"), "incomplete-compatibility-evidence", "candidate target platform is unsupported")
            if expected is not None and actual != expected:
                raise ConsumerFailure("incompatible-constraints", "candidate target platform is incompatible")
        elif key == "kotlinMetadataVersion":
            require(isinstance(actual, list), "incomplete-compatibility-evidence", "candidate Kotlin metadata version is missing or malformed")
            if actual != expected:
                raise ConsumerFailure("incompatible-constraints", "candidate Kotlin metadata version is incompatible")
        elif key == "multiReleaseSelection":
            require(isinstance(actual, int) and not isinstance(actual, bool) and actual >= 8, "incomplete-compatibility-evidence", "candidate multi-release selection is malformed")
            if actual != expected:
                raise ConsumerFailure("incompatible-constraints", "candidate multi-release selection is incompatible")
        else:
            require(isinstance(actual, str) and actual, "incomplete-compatibility-evidence", f"candidate {key} is missing or malformed")
            if actual != expected:
                raise ConsumerFailure("incompatible-constraints", f"candidate {key} is incompatible")
    return {"status": "compatible", "candidate": copy.deepcopy(supplied), "constraints": copy.deepcopy(constraints)}


def validate_mapping(model: Dict[str, Any], source: Dict[str, Any], binaries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    facts = [
        obj(item, "mapping fact")
        for item in model.get("extensionFacts", [])
        if isinstance(item, dict) and item.get("vocabulary") == MAPPING_PROFILE and item.get("family") == "java-jvm-mapping"
    ]
    require(len(facts) == 1, "incomplete-mapping", "one exact Java/JVM mapping fact is required")
    fact = facts[0]
    require(fact.get("version") == PROFILE_VERSION, "unsupported-required-profile", "Java/JVM mapping fact uses an unsupported profile version")
    require(fact.get("scope") == {"sourceSymbol": source["id"]}, "invalid-mapping", "mapping scope is not the exact source symbol")
    payload = obj(fact.get("payload"), "Java/JVM mapping payload")
    require(payload.get("profileVersion") == PROFILE_VERSION and payload.get("resolution") == "established", "incomplete-mapping", "mapping is not established at the supported profile version")
    require(payload.get("sourceSymbol") == source["id"], "invalid-mapping", "mapping source is not the exact source identity")
    target_ids = payload.get("binarySymbols")
    require(isinstance(target_ids, list) and target_ids, "invalid-mapping", "mapping does not contain a target set")
    checked_target_ids = [local_id(target_id, "mapping binary target") for target_id in target_ids]
    require(len(set(checked_target_ids)) == len(checked_target_ids), "invalid-mapping", "mapping does not contain a unique target set")
    targets: List[Dict[str, Any]] = []
    for target_id in checked_target_ids:
        require(target_id in binaries, "invalid-mapping", "mapping target does not resolve to a JVM binary identity")
        targets.append(binaries[target_id])
    require(payload.get("mappingKind") in MAPPING_KINDS, "invalid-mapping", "mapping kind is unsupported")
    evidence = payload.get("evidence")
    require(isinstance(evidence, list) and evidence, "missing-mapping-evidence", "established mapping requires authoritative evidence")
    for item in evidence:
        record = obj(item, "mapping evidence")
        require(set(record) == {"kind", "producer", "digest"} and record.get("kind") in EVIDENCE_KINDS, "invalid-evidence", "mapping evidence kind is unsupported")
        uri(record.get("producer"), "mapping evidence producer")
        digest(record.get("digest"), "mapping evidence digest")

    coverage = [
        obj(item, "mapping completeness statement")
        for item in model.get("completenessStatements", [])
        if isinstance(item, dict) and item.get("vocabulary") == MAPPING_PROFILE and item.get("family") == "java-jvm-mapping" and item.get("scope") == {"sourceSymbol": source["id"]}
    ]
    require(len(coverage) == 1, "incomplete-mapping-coverage", "mapping coverage is not complete for the exact source and selected artifact")
    require(coverage[0].get("version") == PROFILE_VERSION, "unsupported-required-profile", "mapping coverage uses an unsupported profile version")
    require(coverage[0].get("status") == "complete", "incomplete-mapping-coverage", "mapping coverage is not complete for the exact source and selected artifact")
    return {
        "resolution": payload["resolution"],
        "source": copy.deepcopy(source["identity"]),
        "targets": copy.deepcopy(targets),
        "mappingKind": payload["mappingKind"],
        "evidence": copy.deepcopy(evidence),
        "coverage": "complete",
    }


def project(document: Dict[str, Any], candidate: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    require(document.get("documentType") == "semantic-document", "malformed-model", "unsupported document type")
    require(document.get("schema") == CSMI_SCHEMA and document.get("semanticModelVersion") == CORE_VERSION and document.get("serializationVersion") == SERIALIZATION_VERSION, "unsupported-core", "unsupported CSMI core version")
    validate_provenance(document)
    models = document.get("semanticModels")
    require(isinstance(models, list) and len(models) == 1, "unsupported-model-shape", "this consumer requires exactly one semantic model")
    model = obj(models[0], "semantic model")
    validate_uses(model)

    selectors = model.get("artifactSelectors")
    require(isinstance(selectors, list) and len(selectors) == 1, "incomplete-artifact-evidence", "one exact Maven artifact selector is required")
    binary_selector = validate_selector(selectors[0], MAVEN_PURL, "jar", "binary artifact selector")

    raw_symbols = model.get("symbols")
    require(isinstance(raw_symbols, list) and raw_symbols, "malformed-model", "symbols must be non-empty")
    symbols: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for raw in raw_symbols:
        symbol = obj(raw, "symbol")
        sid = local_id(symbol.get("id"), "symbol ID")
        require(sid not in by_id, "malformed-model", "symbol IDs must be unique local handles")
        by_id[sid] = symbol
        symbols.append(symbol)

    source_symbol = find_unique(symbols, lambda symbol: symbol.get("scheme") == SOURCE_PROFILE, "Java source symbol")
    binary_symbol = find_unique(symbols, lambda symbol: symbol.get("scheme") == BINARY_PROFILE, "JVM binary symbol")
    source_identity = validate_source_symbol(source_symbol, [{"purl": SOURCE_PURL, "digests": [{"algorithm": "sha-256", "coverage": "source-archive", "value": "2222222222222222222222222222222222222222222222222222222222222222"}]}])
    binary_identity = validate_binary_symbol(binary_symbol, [binary_selector])
    source_record = {"id": source_symbol["id"], "identity": source_identity}
    binaries = {symbol["id"]: {"id": symbol["id"], "identity": validate_binary_symbol(symbol, [binary_selector])} for symbol in symbols if symbol.get("scheme") == BINARY_PROFILE}
    mapping = validate_mapping(model, source_record, binaries)
    compatibility = validate_compatibility(model, candidate)

    return {
        "resultFormatVersion": "csmi-demo-java-jvm-profile-result/1",
        "status": "complete",
        "profiles": [
            {"identifier": SOURCE_PROFILE, "version": PROFILE_VERSION, "scheme": SOURCE_PROFILE, "schemeVersion": PROFILE_VERSION},
            {"identifier": BINARY_PROFILE, "version": PROFILE_VERSION, "scheme": BINARY_PROFILE, "schemeVersion": PROFILE_VERSION},
            {"identifier": MAPPING_PROFILE, "version": PROFILE_VERSION, "scheme": None, "schemeVersion": None},
            {"identifier": COMPATIBILITY_PROFILE, "version": PROFILE_VERSION, "scheme": None, "schemeVersion": None},
        ],
        "artifact": copy.deepcopy(binary_selector),
        "meanings": {
            "sourceIdentity": copy.deepcopy(source_identity),
            "binaryIdentity": copy.deepcopy(binary_identity),
            "mapping": mapping,
            "compatibility": compatibility,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", type=Path, default=Path(__file__).parent / "fixtures" / "java-jvm-mapping.json")
    parser.add_argument("--java-release", type=int, help="candidate Java runtime release")
    parser.add_argument("--class-file-major", type=int, help="candidate JVM class-file major version")
    parser.add_argument("--target-platform", choices=("jvm", "android"), help="candidate target platform")
    args = parser.parse_args(argv)
    candidate = {key: value for key, value in (("javaRelease", args.java_release), ("classFileMajor", args.class_file_major), ("targetPlatform", args.target_platform)) if value is not None}
    try:
        result = project(load(args.document), candidate)
    except ConsumerFailure as exc:
        print(json.dumps({"status": "failed", "failure": {"code": exc.code, "message": exc.message}}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
