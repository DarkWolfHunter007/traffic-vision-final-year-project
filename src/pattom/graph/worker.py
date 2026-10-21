"""Subprocess worker for graph node execution.

Allows clean process isolation and hard termination on Windows without freezing or orphaning tasks.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from pattom.graph.nodes import NODE_TYPES


def main() -> None:
    p = argparse.ArgumentParser(description="Pattom node worker")
    p.add_argument("--type", required=True, help="Node type name")
    p.add_argument("--inputs", required=True, help="JSON encoded inputs dict")
    p.add_argument("--params", required=True, help="JSON encoded params dict")
    p.add_argument("--out", required=True, help="Output JSON path")
    args = p.parse_args()

    node_type = NODE_TYPES.get(args.type)
    if not node_type or not node_type.run:
        sys.stderr.write(f"Error: unknown or unrunnable node type {args.type!r}\n")
        sys.exit(2)

    try:
        inputs = json.loads(args.inputs)
        params = json.loads(args.params)
    except Exception as e:
        sys.stderr.write(f"Error decoding arguments: {e}\n")
        sys.exit(2)

    try:
        outputs = node_type.run(inputs, params)
        if not isinstance(outputs, dict):
            raise TypeError(f"Node {args.type} run() returned {type(outputs)}, expected dict")
        Path(args.out).write_text(json.dumps(outputs, indent=2), encoding="utf-8")
        sys.exit(0)
    except Exception as error:
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
