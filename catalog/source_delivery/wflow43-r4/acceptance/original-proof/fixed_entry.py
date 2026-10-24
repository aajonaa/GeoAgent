"""Fixed CPU-only prototype entry. stdin is arguments JSON, never Python code."""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
cache = HERE / "cache/fixed-entry"
for name, suffix in (("MPLCONFIGDIR", "matplotlib"), ("NUMBA_CACHE_DIR", "numba"),
                     ("XDG_CACHE_HOME", "xdg")):
    path = cache / suffix
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
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
            raise ImportError("Model imports forbidden in this CPU-only entry")


def no_network(*args, **kwargs):
    raise RuntimeError("Network forbidden in this CPU-only entry")


sys.meta_path.insert(0, NoModels())
socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.create_connection = no_network
sys.path.insert(0, os.environ["WFLOW_HOST_CANDIDATE"])
from geological_agent.contracts import ToolCall
from geological_agent.tools import ToolExecutionContext
from geological_agent.settings import Settings
from kernel_adapter import NAME, native_executor


def main():
    arguments = sys.stdin.read(65537)
    if len(arguments) > 65536:
        print(json.dumps({"status": "error", "error": {"code": "invalid_arguments", "message": "Oversized request"}}))
        return 1
    workspace = Path(os.environ["WFLOW_WORKSPACE"])
    context = ToolExecutionContext("wflow-fixed-cpu", workspace, (NAME,), Settings(tool_timeout_seconds=0), Event())
    result = native_executor().execute(ToolCall("wflow-fixed", NAME, arguments), context)
    print(json.dumps(asdict(result), allow_nan=False, sort_keys=True))
    return 0 if result.status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
