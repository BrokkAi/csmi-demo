"""A deliberately narrow, dependency-free CSMI v0.1 dataflow consumer."""

from __future__ import annotations

import hashlib
import json
import posixpath
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, unquote

CONSUMER_NAME = "brokkai.csmi.minimal-dataflow"
CONSUMER_VERSION = "0.1.0"
SCHEMA = "https://csmi.brokk.ai/schema/0.1/schema.json"
SEMANTIC_MEDIA_TYPE = "application/vnd.csmi.semantic-model.v0.1+json"


class ConsumerFailure(Exception):
    """A typed fail-closed consumer outcome."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass(frozen=True)
class LoadedPack:
    digest: str
    models: tuple[dict[str, Any], ...]
    provenance: dict[str, dict[str, Any]]


def _require(condition: bool, code: str, message: str, **details: Any) -> None:
    if not condition:
        raise ConsumerFailure(code, message, **details)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerFailure("malformed-input", f"cannot read JSON: {path}", error=str(exc)) from exc


def _canonical_json(value: Any) -> bytes:
    try:
        # CSMI requires RFC 8785. The supported subset contains no numbers or
        # escaped keys for which Python's deterministic encoding differs.
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as exc:
        raise ConsumerFailure("malformed-pack", "pack JSON cannot be canonicalized", error=str(exc)) from exc


def _closed_object(value: Any, required: set[str], allowed: set[str], context: str) -> dict[str, Any]:
    _require(isinstance(value, dict), "malformed-pack", f"{context} must be an object")
    missing = sorted(required - value.keys())
    unknown = sorted(value.keys() - allowed)
    _require(not missing and not unknown, "malformed-pack", f"invalid fields in {context}", missing=missing, unknown=unknown)
    return value


def _parse_purl(value: str) -> tuple[Any, ...]:
    _require(isinstance(value, str) and value.startswith("pkg:"), "malformed-pack", "invalid PURL")
    _require("#" not in value, "unsupported-semantics", "PURL subpaths are not supported", purl=value)
    main, _, query = value[4:].partition("?")
    package, marker, version = main.rpartition("@")
    _require(bool(marker and package and version), "unsupported-semantics", "only exact-version PURLs are supported", purl=value)
    parts = package.split("/")
    _require(len(parts) >= 2 and all(parts), "malformed-pack", "invalid PURL components", purl=value)
    qualifiers = tuple(sorted((unquote(key).lower(), unquote(val)) for key, val in parse_qsl(query, keep_blank_values=True)))
    return parts[0].lower(), tuple(map(unquote, parts[1:-1])), unquote(parts[-1]), unquote(version), qualifiers


def _digest_map(items: Any, *, context: str) -> dict[tuple[str, str], str]:
    _require(isinstance(items, list) and items, "malformed-pack", f"{context} digests must be non-empty")
    result: dict[tuple[str, str], str] = {}
    for item in items:
        _closed_object(item, {"algorithm", "coverage", "value"}, {"algorithm", "coverage", "canonicalization", "value"}, context)
        key = (item["algorithm"], item["coverage"])
        _require(key not in result, "malformed-pack", f"duplicate digest in {context}", algorithm=key[0], coverage=key[1])
        result[key] = item["value"]
    return result


def _selector_matches(selector: dict[str, Any], artifact: dict[str, Any]) -> bool:
    _closed_object(selector, {"purl"}, {"purl", "versionRange", "digests"}, "artifact selector")
    _require("versionRange" not in selector, "unsupported-semantics", "VERS artifact selectors are unsupported")
    if _parse_purl(selector["purl"]) != _parse_purl(artifact["purl"]):
        return False
    if "digests" in selector:
        wanted = _digest_map(selector["digests"], context="selector")
        actual = _digest_map(artifact.get("digests"), context="candidate artifact")
        for key, value in wanted.items():
            _require(key in actual, "artifact-applicability-indeterminate", "candidate lacks a required artifact digest", algorithm=key[0], coverage=key[1])
            if actual[key] != value:
                return False
    return True


def _safe_resource(pack_dir: Path, logical_path: str) -> Path:
    _require(isinstance(logical_path, str) and logical_path and "\\" not in logical_path, "integrity-failure", "unsafe resource path", path=logical_path)
    normalized = posixpath.normpath(logical_path)
    _require(normalized == logical_path and not normalized.startswith("../") and not normalized.startswith("/"), "integrity-failure", "unsafe resource path", path=logical_path)
    return pack_dir.joinpath(*logical_path.split("/"))


def _load_canonical(path: Path, context: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumerFailure("malformed-pack", f"cannot parse {context}", path=str(path), error=str(exc)) from exc
    _require(isinstance(value, dict), "malformed-pack", f"{context} must be an object")
    _require(raw == _canonical_json(value), "malformed-pack", f"{context} is not canonical JSON", path=str(path))
    return value, raw


def load_pack(pack_dir: Path, expected_digest: str | None) -> LoadedPack:
    manifest, manifest_raw = _load_canonical(pack_dir / "manifest.json", "pack manifest")
    _closed_object(manifest, {"documentType", "schema", "packFormatVersion", "assembler", "license", "resources"}, {"documentType", "schema", "packFormatVersion", "assembler", "license", "resources", "createdAt", "derivedFrom"}, "pack manifest")
    _require(manifest["documentType"] == "pack-manifest" and manifest["schema"] == SCHEMA and manifest["packFormatVersion"] == "0.1", "unsupported-semantics", "unsupported pack format")
    pack_digest = hashlib.sha256(manifest_raw).hexdigest()
    _require(expected_digest is None or expected_digest == pack_digest, "integrity-failure", "expected pack digest does not match", expected=expected_digest, actual=pack_digest)
    resources = manifest["resources"]
    _require(isinstance(resources, list) and resources, "malformed-pack", "pack resources must be non-empty")
    seen: set[str] = set()
    models: list[dict[str, Any]] = []
    all_provenance: dict[str, dict[str, Any]] = {}
    for descriptor in resources:
        _closed_object(descriptor, {"path", "role", "mediaType", "size", "digest"}, {"path", "role", "mediaType", "size", "digest", "license", "schemaIdentifier", "licenseReference"}, "resource descriptor")
        logical_path = descriptor["path"]
        _require(logical_path not in seen, "malformed-pack", "duplicate resource path", path=logical_path)
        seen.add(logical_path)
        resource_path = _safe_resource(pack_dir, logical_path)
        try:
            raw = resource_path.read_bytes()
        except OSError as exc:
            raise ConsumerFailure("integrity-failure", "missing pack resource", path=logical_path, error=str(exc)) from exc
        digest = descriptor["digest"]
        _closed_object(digest, {"algorithm", "value"}, {"algorithm", "value"}, "resource digest")
        _require(digest["algorithm"] == "sha-256" and len(raw) == descriptor["size"] and hashlib.sha256(raw).hexdigest() == digest["value"], "integrity-failure", "pack resource size or digest mismatch", path=logical_path)
        if descriptor["role"] != "semantic-document":
            continue
        _require(descriptor["mediaType"] == SEMANTIC_MEDIA_TYPE, "malformed-pack", "semantic resource has wrong media type", path=logical_path)
        document, canonical_raw = _load_canonical(resource_path, "semantic document")
        _require(raw == canonical_raw, "malformed-pack", "semantic resource changed during read", path=logical_path)
        _closed_object(document, {"documentType", "schema", "semanticModelVersion", "serializationVersion", "provenanceRecords", "semanticModels"}, {"documentType", "schema", "semanticModelVersion", "serializationVersion", "provenanceRecords", "semanticModels", "defaultProvenance"}, "semantic document")
        _require(document["documentType"] == "semantic-document" and document["schema"] == SCHEMA and document["semanticModelVersion"] == "0.1" and document["serializationVersion"] == "0.1-json", "unsupported-semantics", "unsupported semantic document version", path=logical_path)
        records = document["provenanceRecords"]
        _require(isinstance(records, list) and records, "malformed-pack", "provenanceRecords must be non-empty")
        record_ids = [record.get("id") for record in records if isinstance(record, dict)]
        _require(len(record_ids) == len(records) and len(set(record_ids)) == len(record_ids), "malformed-pack", "provenance record IDs must be unique")
        for record in records:
            _closed_object(record, {"id", "producer", "generationMethod"}, {"id", "producer", "generationMethod", "inputs", "createdAt", "invocationId", "diagnostic"}, "provenance record")
            _closed_object(record["producer"], {"identifier", "version"}, {"identifier", "version"}, "producer identity")
            qualified_id = f"{hashlib.sha256(raw).hexdigest()}:{record['id']}"
            all_provenance[qualified_id] = record
        default = document.get("defaultProvenance")
        _require(default is None or default in record_ids, "malformed-pack", "default provenance is unresolved", provenance=default)
        _require(isinstance(document["semanticModels"], list) and document["semanticModels"], "malformed-pack", "semanticModels must be non-empty")
        for model in document["semanticModels"]:
            _require(isinstance(model, dict), "malformed-pack", "semantic model must be an object")
            model["__provenance_ids"] = record_ids
            model["__default_provenance"] = default
            model["__document_digest"] = hashlib.sha256(raw).hexdigest()
            models.append(model)
    _require(models, "malformed-pack", "pack contains no semantic documents")
    return LoadedPack(pack_digest, tuple(models), all_provenance)


def _identity(symbol: dict[str, Any], inherited_selectors: Any) -> dict[str, Any]:
    required = {"scheme", "schemeVersion", "stability", "descriptors"}
    _require(required <= symbol.keys(), "malformed-pack", "symbol lacks structural identity", symbol=symbol.get("id"))
    return {"artifactSelectors": symbol.get("artifactSelectors", inherited_selectors), "scheme": symbol["scheme"], "schemeVersion": symbol["schemeVersion"], "stability": symbol["stability"], "descriptors": symbol["descriptors"]}


def _identity_key(value: Any) -> tuple[Any, ...]:
    """Create an exact hashable key without display-string serialization."""
    if isinstance(value, dict):
        return ("object", *((key, _identity_key(item)) for key, item in sorted(value.items())))
    if isinstance(value, list):
        return ("array", *(_identity_key(item) for item in value))
    return ("value", type(value).__name__, value)


def _provenance_for(item: dict[str, Any], model: dict[str, Any]) -> tuple[str, ...]:
    refs = item.get("provenance")
    if refs is None:
        default = model.get("__default_provenance")
        _require(default is not None, "malformed-pack", "fact has no provenance")
        refs = [default]
    known = set(model["__provenance_ids"])
    _require(isinstance(refs, list) and refs and all(ref in known for ref in refs), "malformed-pack", "fact provenance is unresolved", provenance=refs)
    return tuple(f"{model['__document_digest']}:{ref}" for ref in refs)


def _summary_edges(models: Iterable[dict[str, Any]], artifact: dict[str, Any], call_identities: list[dict[str, Any]]) -> tuple[dict[tuple[Any, ...], bool], dict[str, Any]]:
    matched_models = []
    for model in models:
        selectors = model.get("artifactSelectors")
        _require(isinstance(selectors, list) and selectors, "malformed-pack", "semantic model has no artifact selectors")
        if any(_selector_matches(selector, artifact) for selector in selectors):
            matched_models.append(model)
    _require(matched_models, "artifact-mismatch", "no semantic model applies to the candidate artifact")
    _require(len(matched_models) == 1, "unsupported-semantics", "multiple semantic models apply to the candidate artifact")
    model = matched_models[0]
    _require(not model.get("compatibilityConstraints"), "unsupported-semantics", "compatibility constraints are unsupported")
    _require(not model.get("consumerResolvedDependencies"), "unresolved-symbol", "consumer-resolved declaration dependencies are unsupported", dependencies=model.get("consumerResolvedDependencies"))
    required_vocabularies = [use for use in model.get("vocabularyUses", []) if use.get("requirement") == "required"]
    _require(not required_vocabularies, "unsupported-semantics", "required vocabulary is unsupported", vocabularies=required_vocabularies)
    symbols = model.get("symbols")
    _require(isinstance(symbols, list) and symbols, "malformed-pack", "semantic model has no symbols")
    identities: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        symbol_id = symbol.get("id") if isinstance(symbol, dict) else None
        _require(isinstance(symbol_id, str) and symbol_id not in identities, "malformed-pack", "symbol handles must be unique", symbol=symbol_id)
        identities[symbol_id] = _identity(symbol, model["artifactSelectors"])
    declarations = {decl.get("symbol"): decl for decl in model.get("declarations", []) if isinstance(decl, dict)}
    summaries = {summary.get("callable"): summary for summary in model.get("procedureSummaries", []) if isinstance(summary, dict)}
    completeness: dict[str, dict[str, Any]] = {}
    for statement in model.get("completenessStatements", []):
        if not isinstance(statement, dict) or statement.get("family") != "procedure-summaries":
            continue
        callable_id = statement.get("scope", {}).get("callable")
        _require(callable_id not in completeness, "malformed-pack", "conflicting procedure-summary completeness", callable=callable_id)
        completeness[callable_id] = statement
    transfers: dict[tuple[Any, ...], bool] = {}
    used_provenance: set[str] = set()
    for call_identity in call_identities:
        matching = [symbol_id for symbol_id, identity in identities.items() if identity == call_identity]
        _require(matching, "unresolved-symbol", "call target has no exact structural symbol match", identity=call_identity)
        _require(len(matching) == 1, "unresolved-symbol", "call target structural identity is ambiguous", identity=call_identity)
        symbol_id = matching[0]
        declaration = declarations.get(symbol_id)
        _require(declaration is not None and declaration.get("category") == "callable", "unresolved-symbol", "matched symbol has no callable declaration", symbol=symbol_id)
        used_provenance.update(_provenance_for(declaration, model))
        shape = declaration.get("callable")
        _require(isinstance(shape, dict) and shape.get("receiver") is None and len(shape.get("parameters", [])) == 1 and len(shape.get("results", [])) == 1, "unsupported-semantics", "unsupported callable shape", symbol=symbol_id)
        statement = completeness.get(symbol_id)
        _require(statement is not None and statement.get("status") == "complete", "incomplete-evidence", "procedure-summary evidence is not complete", symbol=symbol_id, status=None if statement is None else statement.get("status"))
        used_provenance.update(_provenance_for(statement, model))
        summary = summaries.get(symbol_id)
        _require(summary is not None and isinstance(summary.get("transfers"), list), "malformed-pack", "complete callable lacks a procedure summary", symbol=symbol_id)
        has_transfer = False
        for transfer in summary["transfers"]:
            _require(isinstance(transfer, dict), "malformed-pack", "transfer must be an object", symbol=symbol_id)
            _require("projection" not in transfer.get("source", {}) and "projection" not in transfer.get("destination", {}), "unsupported-semantics", "projections are unsupported", symbol=symbol_id)
            source = transfer.get("source", {}).get("root")
            destination = transfer.get("destination", {}).get("root")
            _require(source == {"phase": "input", "role": "parameter", "position": 0} and destination == {"phase": "output", "role": "result", "position": 0}, "unsupported-semantics", "only parameter[0] to result[0] transfers are supported", symbol=symbol_id)
            used_provenance.update(_provenance_for(transfer, model))
            has_transfer = True
        transfers[_identity_key(call_identity)] = has_transfer
    return transfers, {"records": sorted(used_provenance)}


def _validate_analysis(analysis: Any) -> tuple[set[str], list[tuple[str, str]], list[dict[str, Any]], list[dict[str, str]]]:
    _require(isinstance(analysis, dict), "malformed-input", "analysis input must be an object")
    _require(set(analysis) == {"formatVersion", "nodes", "edges", "externalCalls", "queries"} and analysis["formatVersion"] == "minimal-dataflow-input/1", "malformed-input", "unsupported analyzer input")
    nodes = analysis["nodes"]
    _require(isinstance(nodes, list) and nodes and all(isinstance(node, str) for node in nodes) and len(set(nodes)) == len(nodes), "malformed-input", "analysis nodes must be unique strings")
    node_set = set(nodes)
    edges: list[tuple[str, str]] = []
    _require(isinstance(analysis["edges"], list), "malformed-input", "analysis edges must be an array")
    for edge in analysis["edges"]:
        _require(isinstance(edge, list) and len(edge) == 2 and all(node in node_set for node in edge), "malformed-input", "analysis edge references an invalid node", edge=edge)
        edges.append((edge[0], edge[1]))
    calls = analysis["externalCalls"]
    _require(isinstance(calls, list), "malformed-input", "externalCalls must be an array")
    for call in calls:
        _require(isinstance(call, dict) and set(call) == {"id", "target", "arguments", "results"}, "malformed-input", "invalid external call")
        _require(isinstance(call["arguments"], list) and len(call["arguments"]) == 1 and isinstance(call["results"], list) and len(call["results"]) == 1, "malformed-input", "consumer supports exactly one argument and result per call", call=call.get("id"))
        _require(call["arguments"][0] in node_set and call["results"][0] in node_set, "malformed-input", "external call references an invalid node", call=call.get("id"))
        _require(isinstance(call["target"], dict) and set(call["target"]) == {"artifactSelectors", "scheme", "schemeVersion", "stability", "descriptors"}, "malformed-input", "call target must contain exact structural identity", call=call.get("id"))
    queries = analysis["queries"]
    _require(isinstance(queries, list) and queries, "malformed-input", "queries must be a non-empty array")
    query_ids: set[str] = set()
    for query in queries:
        _require(isinstance(query, dict) and set(query) == {"id", "sourceNode", "sinkNode"}, "malformed-input", "invalid analyzer query")
        _require(isinstance(query["id"], str) and query["id"] not in query_ids, "malformed-input", "query IDs must be unique", query=query.get("id"))
        _require(query["sourceNode"] in node_set and query["sinkNode"] in node_set, "malformed-input", "query references an invalid analyzer node", query=query["id"])
        query_ids.add(query["id"])
    return node_set, edges, calls, queries


def _reachable(nodes: set[str], edges: Iterable[tuple[str, str]], source: str) -> set[str]:
    adjacency = {node: [] for node in nodes}
    for edge_source, destination in edges:
        adjacency[edge_source].append(destination)
    reached = {source}
    queue = deque(reached)
    while queue:
        for destination in adjacency[queue.popleft()]:
            if destination not in reached:
                reached.add(destination)
                queue.append(destination)
    return reached


def _metric(numerator: int, denominator: int) -> dict[str, Any]:
    result: dict[str, Any] = {"defined": denominator > 0, "numerator": numerator, "denominator": denominator}
    if denominator:
        result["value"] = numerator / denominator
    return result


def run(*, analysis: dict[str, Any], artifact: dict[str, Any], labels: dict[str, Any], scenario_identity: dict[str, Any], pack: LoadedPack | None) -> dict[str, Any]:
    nodes, edges, calls, queries = _validate_analysis(analysis)
    analysis_digest = hashlib.sha256(_canonical_json(analysis)).hexdigest()
    _require(isinstance(artifact, dict) and set(artifact) == {"purl", "digests"}, "malformed-input", "artifact identity must contain exact PURL and digests")
    _parse_purl(artifact["purl"])
    _digest_map(artifact["digests"], context="candidate artifact")
    provenance: dict[str, Any] = {"records": []}
    if pack is not None:
        transfers, used_provenance = _summary_edges(pack.models, artifact, [call["target"] for call in calls])
        provenance = {"records": [pack.provenance[record_id] for record_id in used_provenance["records"]]}
        for call in calls:
            key = _identity_key(call["target"])
            if transfers[key]:
                edges.append((call["arguments"][0], call["results"][0]))

    # Source/sink queries and observed results come solely from analyzer input.
    observed_by_id: dict[str, bool] = {}
    reachability: dict[str, set[str]] = {}
    for query in queries:
        if query["sourceNode"] not in reachability:
            reachability[query["sourceNode"]] = _reachable(nodes, edges, query["sourceNode"])
        observed_by_id[query["id"]] = query["sinkNode"] in reachability[query["sourceNode"]]

    # Expected labels are deliberately consulted only after analysis completes.
    _require(isinstance(labels, dict) and labels.get("formatVersion") == "csmi-demo-labels/1" and isinstance(labels.get("flows"), list), "malformed-input", "invalid labels document")
    for flow in labels["flows"]:
        _require(isinstance(flow, dict) and set(flow) == {"id", "expectedFlow"}, "malformed-input", "invalid flow label")
        _require(flow["id"] in observed_by_id and isinstance(flow["expectedFlow"], bool), "malformed-input", "flow label does not match an analyzer query", label=flow.get("id"))
    _require({flow["id"] for flow in labels["flows"]} == set(observed_by_id), "malformed-input", "labels and analyzer queries must have identical IDs")

    flow_results = []
    counts = {"truePositive": 0, "falsePositive": 0, "falseNegative": 0, "trueNegative": 0}
    for flow in labels["flows"]:
        observed = observed_by_id[flow["id"]]
        if flow["expectedFlow"] and observed:
            classification = "TP"
            counts["truePositive"] += 1
        elif flow["expectedFlow"]:
            classification = "FN"
            counts["falseNegative"] += 1
        elif observed:
            classification = "FP"
            counts["falsePositive"] += 1
        else:
            classification = "TN"
            counts["trueNegative"] += 1
        flow_results.append({"id": flow["id"], "expectedFlow": flow["expectedFlow"], "observedFlow": observed, "classification": classification})
    tp, fp, fn = counts["truePositive"], counts["falsePositive"], counts["falseNegative"]
    return {
        "resultFormatVersion": "csmi-demo-consumer-result/1",
        "status": "complete",
        "consumer": {"name": CONSUMER_NAME, "version": CONSUMER_VERSION},
        "analysis": {"formatVersion": analysis["formatVersion"], "canonicalSha256": analysis_digest},
        "scenario": scenario_identity,
        "artifact": artifact,
        "pack": {"state": "on" if pack else "off", **({"digest": {"algorithm": "sha-256", "value": pack.digest}} if pack else {})},
        "provenance": provenance,
        "flows": flow_results,
        "counts": counts,
        "metrics": {"precision": _metric(tp, tp + fp), "recall": _metric(tp, tp + fn)},
    }
