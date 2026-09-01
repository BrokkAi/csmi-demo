"""Command line entry point for the minimal dataflow consumer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .consumer import CONSUMER_NAME, CONSUMER_VERSION, ConsumerFailure, load_json, load_pack, run


def _identity_value(path: Path, field: str) -> Any:
    value = load_json(path)
    if isinstance(value, dict) and field in value:
        return value[field]
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--scenario-identity-file", type=Path, required=True)
    parser.add_argument("--pack", required=True, help="'off' or a CSMI pack directory")
    parser.add_argument("--expected-pack-digest-file", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        loaded_pack = None
        if args.pack != "off":
            expected = None
            if args.expected_pack_digest_file:
                expected_value = _identity_value(args.expected_pack_digest_file, "packDigest")
                expected = expected_value.get("value") if isinstance(expected_value, dict) else expected_value
                if not isinstance(expected, str):
                    raise ConsumerFailure("malformed-input", "expected pack digest file contains no digest")
            loaded_pack = load_pack(Path(args.pack), expected)
        result = run(
            analysis=load_json(args.analysis),
            artifact=load_json(args.artifact),
            labels=load_json(args.labels),
            scenario_identity=_identity_value(args.scenario_identity_file, "scenarioIdentity"),
            pack=loaded_pack,
        )
        exit_code = 0
    except ConsumerFailure as exc:
        result = {"resultFormatVersion": "csmi-demo-consumer-result/1", "status": "failed", "consumer": {"name": CONSUMER_NAME, "version": CONSUMER_VERSION}, "failure": exc.as_dict()}
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
