"""Graph validation, content-hash caching, and execution engine.

Supports:
- Topological sorting and strict port-type validation.
- Content-hash caching: hash(inputs content + params + config contents + weights + code rev).
- Subprocess execution with cooperative cancellation (can kill long-running YOLO/ffmpeg on Windows).
- Failure isolation (failed node blocks only its downstream dependents).
- Single-node target execution (runs only the target node and its uncompleted ancestors).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from pattom.graph.nodes import NODE_TYPES
from pattom.paths import REPO_ROOT
from pattom.runmeta import code_revision, sha256_file

CACHE_DIR = REPO_ROOT / ".cache" / "graph"


class GraphError(ValueError):
    """Raised when a graph spec is invalid."""


@dataclass
class GraphRunResult:
    order: list[str]
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    elapsed: dict[str, float] = field(default_factory=dict)
    logs: dict[str, list[str]] = field(default_factory=dict)


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


def get_ancestors(spec: dict[str, Any], target_node_id: str) -> set[str]:
    """Return all node IDs needed to execute target_node_id (including itself)."""
    needed = {target_node_id}
    wiring: dict[str, set[str]] = {n: set() for n in spec.get("nodes", {})}
    for edge in spec.get("edges", []):
        src, _ = _endpoint(edge["from"])
        dst, _ = _endpoint(edge["to"])
        wiring[dst].add(src)

    stack = [target_node_id]
    while stack:
        curr = stack.pop()
        for parent in wiring.get(curr, ()):
            if parent not in needed:
                needed.add(parent)
                stack.append(parent)
    return needed


def _resolve_file_path(val: Any) -> Path | None:
    if isinstance(val, (str, Path)) and str(val).strip():
        p = Path(val)
        candidate = p if p.is_absolute() else REPO_ROOT / p
        if candidate.is_file():
            return candidate
    return None


def compute_cache_key(node_type_name: str, inputs: dict[str, Any], params: dict[str, Any]) -> str:
    """Hash of inputs content + params + config contents + model weights + code rev."""
    h = hashlib.sha256()
    h.update(node_type_name.encode("utf-8"))
    h.update(code_revision().encode("utf-8"))

    # Hash input files by content
    for port_name in sorted(inputs.keys()):
        val = inputs[port_name]
        p = _resolve_file_path(val)
        if p and p.is_file():
            h.update(port_name.encode("utf-8"))
            h.update(sha256_file(p).encode("utf-8"))
        else:
            h.update(f"{port_name}:{val}".encode("utf-8"))

    # Hash parameters and any referenced config/model files
    for k in sorted(params.keys()):
        val = params[k]
        h.update(k.encode("utf-8"))
        p = _resolve_file_path(val)
        if p and p.is_file():
            h.update(sha256_file(p).encode("utf-8"))
            # If it's a YAML config, also hash any referenced weights or subfiles
            if p.suffix.lower() in (".yaml", ".yml"):
                try:
                    cfg_data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                    if isinstance(cfg_data, dict):
                        weights_path = cfg_data.get("weights")
                        wp = _resolve_file_path(weights_path)
                        if wp and wp.is_file():
                            h.update(sha256_file(wp).encode("utf-8"))
                except Exception:
                    pass
        else:
            h.update(json.dumps(val, sort_keys=True, default=str).encode("utf-8"))

    return h.hexdigest()


def check_cache(node_id: str, cache_key: str) -> dict[str, str] | None:
    """Return cached outputs if valid and all output files exist with matching hashes."""
    cache_file = CACHE_DIR / f"{node_id}.cache.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("cache_key") != cache_key:
            return None
        outputs = data.get("outputs", {})
        output_shas = data.get("output_shas", {})
        if not outputs:
            return None
        for port_name, path_str in outputs.items():
            p = Path(path_str)
            if not p.is_file():
                return None
            stored_sha = output_shas.get(port_name)
            if stored_sha and sha256_file(p) != stored_sha:
                return None
        return outputs
    except Exception:
        return None


def write_cache(node_id: str, cache_key: str, outputs: dict[str, str]) -> None:
    """Store cache record for future fast runs."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = CACHE_DIR / f"{node_id}.cache.json"
        output_shas = {}
        for port_name, path_str in outputs.items():
            p = Path(path_str)
            if p.is_file():
                output_shas[port_name] = sha256_file(p)
        payload = {
            "cache_key": cache_key,
            "outputs": outputs,
            "output_shas": output_shas,
            "saved_at": time.time(),
        }
        cache_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass


STATUS_MARK = {"completed": "✓", "cached": "✓", "failed": "✗", "locked": "🔒", "skipped": "–", "cancelled": "■"}


def _describe_file(value: Any) -> str:
    """One line about a stage input or output: name, size, and rows for a table."""
    p = _resolve_file_path(value)
    if not p or not p.is_file():
        return f"{value} (not a file)"
    size = p.stat().st_size
    extra = ""
    if p.suffix.lower() == ".csv":
        with open(p, encoding="utf-8", errors="replace") as f:
            rows = max(sum(1 for _ in f) - 1, 0)
        extra = f", {rows} row(s)"
    elif p.suffix.lower() == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                extra = ", keys: " + ", ".join(list(data)[:8])
        except Exception:
            pass
    try:
        shown = p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        shown = str(p)
    return f"{shown} ({size / 1024:.1f} KB{extra})"


def _short(value: Any) -> str:
    p = _resolve_file_path(value)
    if p and p.is_file():
        try:
            return p.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return str(p)
    text = json.dumps(value) if not isinstance(value, str) else value
    return text if len(text) <= 80 else text[:77] + "..."


def _step_notes(outputs: dict[str, Any], since: float) -> list[str]:
    """Notes the stage wrote into the .run.json files it created in this step."""
    notes: list[str] = []
    folders = {p.parent for p in (_resolve_file_path(v) for v in outputs.values()) if p and p.is_file()}
    for folder in folders:
        for meta in sorted(folder.glob("*.run.json")):
            if meta.stat().st_mtime + 1 < since:
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
            except Exception:
                continue
            raw = [data.get("notes")] + list(((data.get("parameters") or {}).get("notes") or []) if isinstance(
                (data.get("parameters") or {}).get("notes"), list) else [(data.get("parameters") or {}).get("notes")])
            for n in raw:
                if n:
                    notes.append(f"{meta.name}: {n}")
    return notes


def run_graph(
    spec: dict[str, Any],
    target_node_id: str | None = None,
    force: bool = False,
    use_subprocess: bool = False,
    log_callback: Callable[[str, str], None] | None = None,
    status_callback: Callable[[str, str, float | None, str | None], None] | None = None,
    stop_event: threading.Event | None = None,
) -> GraphRunResult:
    """Execute nodes in dependency order with caching, isolation, and optional cancellation."""
    full_order = validate_graph(spec)
    if target_node_id:
        if target_node_id not in spec["nodes"]:
            raise GraphError(f"Target node {target_node_id!r} not in graph")
        needed = get_ancestors(spec, target_node_id)
        order = [n for n in full_order if n in needed]
    else:
        order = full_order

    wiring: dict[tuple[str, str], tuple[str, str]] = {}
    for edge in spec.get("edges", []):
        wiring[_endpoint(edge["to"])] = _endpoint(edge["from"])

    result = GraphRunResult(order=order)
    active_proc: list[subprocess.Popen | None] = [None]

    def _emit_log(node_id: str, line: str) -> None:
        result.logs.setdefault(node_id, []).append(line)
        if log_callback:
            log_callback(node_id, line)

    def _emit_status(node_id: str, st: str, elapsed: float | None = None, err: str | None = None) -> None:
        if st in STATUS_MARK:
            tail = f" in {elapsed:.2f}s" if elapsed else ""
            _emit_log(node_id, f"  {STATUS_MARK[st]} {st.upper()}{tail}" + (f": {err}" if err else ""))
        result.status[node_id] = st
        if err:
            result.errors[node_id] = err
        if elapsed is not None:
            result.elapsed[node_id] = elapsed
        if status_callback:
            status_callback(node_id, st, elapsed, err)

    _emit_log("sys", f"Run plan: {len(order)} step(s) in this order: {' -> '.join(order)}")
    run_start = time.time()
    for step_no, node_id in enumerate(order, start=1):
        _emit_log(node_id, f"── Step {step_no}/{len(order)}: {NODE_TYPES[spec['nodes'][node_id]['type']].label} [{node_id}]")
        if stop_event and stop_event.is_set():
            _emit_status(node_id, "cancelled", 0.0, "Execution cancelled by user")
            continue

        node = spec["nodes"][node_id]
        node_type = NODE_TYPES[node["type"]]
        inputs: dict[str, Any] = {}
        blocked = None
        for port in node_type.inputs:
            source = wiring.get((node_id, port.name))
            if source is None:
                continue
            src_node, src_port = source
            src_status = result.status.get(src_node)
            if src_status not in ("completed", "cached"):
                blocked = src_node
                break
            inputs[port.name] = result.outputs[src_node][src_port]

        if blocked:
            _emit_status(node_id, "skipped", 0.0, f"upstream node {blocked!r} did not complete")
            continue

        params = {**node_type.params, **node.get("params", {})}
        unknown = set(node.get("params", {})) - set(node_type.params)
        missing = sorted(k for k in node_type.required if params.get(k) is None)
        if unknown or missing:
            err_msg = f"unknown params {sorted(unknown)}" if unknown else f"required params not set: {missing}"
            _emit_status(node_id, "failed", 0.0, err_msg)
            continue

        for port_name, val in inputs.items():
            _emit_log(node_id, f"  • input {port_name}: {_describe_file(val)}")
        for k, v in params.items():
            if not k.startswith("_") and v not in (None, ""):
                _emit_log(node_id, f"  • setting {k} = {_short(v)}")

        # Check approval gate
        if node_type.gate_checker:
            gate_info = node_type.gate_checker(params)
            _emit_log(node_id, f"  • gate {gate_info.get('decision')}: {gate_info.get('reason')}")
            if gate_info.get("locked"):
                err_msg = f"Approval gate {gate_info['decision']} locked: {gate_info['reason']}"
                _emit_status(node_id, "locked", 0.0, err_msg)
                continue
            elif not gate_info.get("approved") and gate_info.get("allow_draft"):
                _emit_log(node_id, f"[{node_id}] Notice: Running with unapproved draft definitions ({gate_info['decision']})")

        # Check content-hash cache
        cache_key = compute_cache_key(node_type.name, inputs, params)
        if not force:
            cached_outputs = check_cache(node_id, cache_key)
            if cached_outputs:
                result.outputs[node_id] = cached_outputs
                _emit_log(node_id, "  • inputs, settings and code unchanged: reusing the previous outputs")
                for port_name, val in cached_outputs.items():
                    _emit_log(node_id, f"  • output {port_name}: {_describe_file(val)}")
                _emit_status(node_id, "cached", 0.0)
                continue

        # Execute node
        _emit_log(node_id, "  • no reusable result" + (" (forced re-run)" if force else "") + ": running the stage")
        _emit_status(node_id, "running")
        start_time = time.time()

        if use_subprocess:
            # Subprocess runner allows hard kill on Windows
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as out_tmp:
                out_path = Path(out_tmp.name)
            cmd = [
                sys.executable,
                "-m",
                "pattom.graph.worker",
                "--type",
                node_type.name,
                "--inputs",
                json.dumps(inputs),
                "--params",
                json.dumps(params),
                "--out",
                str(out_path),
            ]
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
                active_proc[0] = proc

                # Stream stdout in background; keep the last line, which names the error on failure
                last_line = [""]

                def _stream_lines(pipe):
                    for line in iter(pipe.readline, ""):
                        line_clean = line.rstrip()
                        if line_clean:
                            last_line[0] = line_clean
                            _emit_log(node_id, line_clean)
                    pipe.close()

                stream_thread = threading.Thread(target=_stream_lines, args=(proc.stdout,), daemon=True)
                stream_thread.start()

                # Poll process with cancel checks
                while proc.poll() is None:
                    if stop_event and stop_event.is_set():
                        try:
                            proc.terminate()
                            proc.wait(timeout=1.0)
                        except Exception:
                            proc.kill()
                        _emit_status(node_id, "cancelled", time.time() - start_time, "Execution cancelled by user")
                        break
                    time.sleep(0.05)

                stream_thread.join(timeout=1.0)
                if stop_event and stop_event.is_set():
                    continue

                if proc.returncode == 0:
                    outputs = json.loads(out_path.read_text(encoding="utf-8"))
                    elapsed = time.time() - start_time
                    result.outputs[node_id] = outputs
                    write_cache(node_id, cache_key, outputs)
                    for port_name, val in outputs.items():
                        _emit_log(node_id, f"  • output {port_name}: {_describe_file(val)}")
                    for note in _step_notes(outputs, start_time):
                        _emit_log(node_id, f"  • note: {note}")
                    _emit_status(node_id, "completed", elapsed)
                else:
                    elapsed = time.time() - start_time
                    err_msg = last_line[0] or f"Process exited with code {proc.returncode}"
                    _emit_status(node_id, "failed", elapsed, err_msg)
            except Exception as error:
                elapsed = time.time() - start_time
                err_msg = f"{type(error).__name__}: {error}"
                _emit_status(node_id, "failed", elapsed, err_msg)
            finally:
                active_proc[0] = None
                if out_path.exists():
                    try:
                        out_path.unlink()
                    except Exception:
                        pass
        else:
            # Direct in-process run (fast, used by tests)
            try:
                outputs = node_type.run(inputs, params)
                elapsed = time.time() - start_time
                result.outputs[node_id] = outputs
                write_cache(node_id, cache_key, outputs)
                for port_name, val in outputs.items():
                    _emit_log(node_id, f"  • output {port_name}: {_describe_file(val)}")
                for note in _step_notes(outputs, start_time):
                    _emit_log(node_id, f"  • note: {note}")
                _emit_status(node_id, "completed", elapsed)
            except Exception as error:
                elapsed = time.time() - start_time
                err_msg = f"{type(error).__name__}: {error}"
                _emit_status(node_id, "failed", elapsed, err_msg)

    _emit_log("sys", f"Checklist after {time.time() - run_start:.1f}s:")
    for node_id in order:
        st = result.status.get(node_id, "not run")
        why = f" ({result.errors[node_id]})" if node_id in result.errors and st != "completed" else ""
        _emit_log("sys", f"  {STATUS_MARK.get(st, '?')} {node_id}: {st}{why}")
    return result
