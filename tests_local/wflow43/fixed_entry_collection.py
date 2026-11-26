"""Fixed native collection entry: JSON stdin only; no runtime installations."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
for key, leaf in (("MPLCONFIGDIR", "matplotlib"), ("NUMBA_CACHE_DIR", "numba"), ("XDG_CACHE_HOME", "xdg")):
    path = HERE / "cache/fixed-collection" / leaf
    path.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(path)
os.environ.update(CUDA_VISIBLE_DEVICES="", NVIDIA_VISIBLE_DEVICES="none", PROJ_NETWORK="OFF",
    LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", GEOTOOL_LANGSMITH_ENABLED="0",
    OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
    NUMBA_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")

import importlib.abc
import json
import socket
import sys
from dataclasses import asdict
from threading import Event


class NoModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"torch", "transformers", "openai", "anthropic", "vllm"}:
            raise ImportError("Models forbidden during collection CPU acceptance")


def forbidden_network(*args, **kwargs):
    raise RuntimeError("Network forbidden during collection CPU acceptance")


sys.meta_path.insert(0, NoModels())
socket.socket.connect = forbidden_network
socket.socket.connect_ex = forbidden_network
socket.create_connection = forbidden_network
sys.path.insert(0, str(HERE / "candidate"))
from geological_agent.bootstrap import build_registry
from geological_agent.contracts import ToolCall
from geological_agent.tools import ToolExecutionContext, ToolExecutor
from geological_agent.settings import Settings

NAME = "EarthWflowKinematicWaveReachStep"


def main():
    text = sys.stdin.read(65537)
    if len(text) > 65536:
        print(json.dumps({"status": "error", "error": {"code": "invalid_arguments", "message": "Oversized request"}}))
        return 1
    registry, _, _ = build_registry()
    workspace = Path(os.environ["WFLOW_COLLECTION_WORKSPACE"])
    result = ToolExecutor(registry).execute(ToolCall("wflow-collection-fixed", NAME, text),
        ToolExecutionContext("collection-cpu", workspace, (NAME,), Settings(tool_timeout_seconds=0), Event()))
    print(json.dumps(asdict(result), sort_keys=True, allow_nan=False))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
