"""Graph validation and execution.

Graph spec (YAML or JSON)::

    nodes: {id: {type: <node type>, params: {...}, pos: [x, y]}}
    edges: [{from: "id.port", to: "id.port"}]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pattom.graph.nodes import NODE_TYPES


class GraphError(ValueError):
    """Raised when a graph spec is invalid."""


@dataclass
class GraphRunResult:
    order: list[str]
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _endpoint(ref: str) -> tuple[str, str]:
    node, sep, port = str(ref).partition(".")
    if not sep or not node or not port:
        raise GraphError(f"Edge endpoint must be 'node.port', got {ref!r}")
    return node, port


def validate_graph(spec: dict[str, Any]) -> list[str]:
    """Check types, ports and wiring; return node ids in topological order."""
    nodes = spec.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise GraphError("Graph needs a non-empty 'nodes' mapping")
    for node_id, node in nodes.items():
        if node.get("type") not in NODE_TYPES:
            raise GraphError(f"Node {node_id!r} has unknown type {node.get('type')!r}")

    fed: set[tuple[str, str]] = set()
    deps: dict[str, set[str]] = {n: set() for n in nodes}
    for edge in spec.get("edges", []):
        src, src_port = _endpoint(edge.get("from"))
        dst, dst_port = _endpoint(edge.get("to"))
        for node_id in (src, dst):
            if node_id not in nodes:
                raise GraphError(f"Edge references unknown node {node_id!r}")
        out = next((p for p in NODE_TYPES[nodes[src]["type"]].outputs if p.name == src_port), None)
        inp = next((p for p in NODE_TYPES[nodes[dst]["type"]].inputs if p.name == dst_port), None)
        if out is None:
            raise GraphError(f"{src!r} has no output port {src_port!r}")
        if inp is None:
            raise GraphError(f"{dst!r} has no input port {dst_port!r}")
        if out.type != inp.type:
            raise GraphError(f"Type mismatch: {src}.{src_port} ({out.type}) -> {dst}.{dst_port} ({inp.type})")
        if (dst, dst_port) in fed:
            raise GraphError(f"Input {dst}.{dst_port} has more than one incoming edge")
        fed.add((dst, dst_port))
        deps[dst].add(src)

    for node_id, node in nodes.items():
        for port in NODE_TYPES[node["type"]].inputs:
            if (node_id, port.name) not in fed:
                raise GraphError(f"Required input {node_id}.{port.name} is not connected")

    order: list[str] = []
    remaining = {n: set(d) for n, d in deps.items()}
    while remaining:
        ready = sorted(n for n, d in remaining.items() if not d)
        if not ready:
            raise GraphError(f"Graph has a cycle among: {', '.join(sorted(remaining))}")
        for node_id in ready:
            order.append(node_id)
            del remaining[node_id]
        for d in remaining.values():
            d.difference_update(ready)
    return order


def load_graph(path: Path) -> dict[str, Any]:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise GraphError("Graph file root must be a mapping")
    return spec


def run_graph(spec: dict[str, Any]) -> GraphRunResult:
    """Execute nodes in dependency order. A failed node blocks only its downstream nodes."""
    order = validate_graph(spec)
    wiring: dict[tuple[str, str], tuple[str, str]] = {}
    for edge in spec.get("edges", []):
        wiring[_endpoint(edge["to"])] = _endpoint(edge["from"])

    result = GraphRunResult(order=order)
    for node_id in order:
        node = spec["nodes"][node_id]
        node_type = NODE_TYPES[node["type"]]
        inputs: dict[str, Any] = {}
        blocked = None
        for port in node_type.inputs:
            source = wiring.get((node_id, port.name))
            if source is None:
                continue
            if result.status.get(source[0]) != "completed":
                blocked = source[0]
                break
            inputs[port.name] = result.outputs[source[0]][source[1]]
        if blocked:
            result.status[node_id] = "skipped"
            result.errors[node_id] = f"upstream node {blocked!r} did not complete"
            continue
        params = {**node_type.params, **node.get("params", {})}
        unknown = set(node.get("params", {})) - set(node_type.params)
        missing = sorted(k for k in node_type.required if params.get(k) is None)
        if unknown or missing:
            result.status[node_id] = "failed"
            result.errors[node_id] = (f"unknown params {sorted(unknown)}" if unknown else f"required params not set: {missing}")
            continue
        try:
            result.outputs[node_id] = node_type.run(inputs, params)
            result.status[node_id] = "completed"
        except Exception as error:  # node failures are reported per node, not raised
            result.status[node_id] = "failed"
            result.errors[node_id] = f"{type(error).__name__}: {error}"
    return result
