"""Command line entry point for the minimal dataflow consumer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from .consumer import CONSUMER_NAME, CONSUMER_VERSION, ConsumerFailure, load_json, load_pack, run
from .scenario import load_scenario, require_pack_available


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True, help="shared scenario directory")
    parser.add_argument("--pack", choices=("off", "on"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    scenario_identity = None
    artifact = None
    try:
        artifact, labels, scenario_identity, pack_record = load_scenario(args.scenario)
        loaded_pack = None
        if args.pack == "on":
            manifest_path, expected = require_pack_available(pack_record)
            pack_dir = args.scenario / Path(manifest_path).parent
            loaded_pack = load_pack(pack_dir, expected)
        result = run(
            analysis=load_json(args.analysis),
            artifact=artifact,
            labels=labels,
            scenario_identity=scenario_identity,
            pack=loaded_pack,
        )
        exit_code = 0
    except ConsumerFailure as exc:
        result = {
            "resultFormatVersion": "csmi-demo-consumer-result/1",
            "status": "failed",
            "consumer": {"name": CONSUMER_NAME, "version": CONSUMER_VERSION},
            "scenario": scenario_identity,
            "artifact": artifact,
            "pack": {"state": args.pack},
            "failure": exc.as_dict(),
        }
        exit_code = 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
