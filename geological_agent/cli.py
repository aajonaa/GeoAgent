import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import uuid
from .bootstrap import create_agent
from .llm import LocalChatClient
from .settings import Settings
from .tracing import configured_trace


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local geological agent. Uses an existing model; starts no web service.")
    parser.add_argument("query", nargs="?")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--skill")
    parser.add_argument("--base-url", default=os.environ.get("GEOTOOL_MODEL_URL", "http://127.0.0.1:8000/v1"))
    parser.add_argument("--model", default=os.environ.get("GEOTOOL_MODEL", "GeoGPT-Research-Project/Qwen2.5-72B-GeoGPT"))
    parser.add_argument("--max-turns", type=int, default=32, help="0 disables the model-turn budget; cancellation remains available")
    parser.add_argument("--tool-timeout", type=float, default=0,
                        help="Tool execution timeout in seconds; 0 (default) disables the deadline")
    parser.add_argument("--stream", action="store_true", help="Show live execution activity; publish final text only after completion checks")
    parser.add_argument("--result-json", type=Path, help="Optional structured acceptance/debug result, separate from the normal answer")
    args = parser.parse_args(argv)
    query = args.query if args.query is not None else input("Task: ")
    workspace = (args.workspace or Path("workspaces") / uuid.uuid4().hex).resolve()
    key = os.environ.get("GEOTOOL_MODEL_KEY", "")
    settings = Settings(max_model_turns=None if args.max_turns == 0 else args.max_turns, tool_timeout_seconds=args.tool_timeout)
    client = LocalChatClient(args.base_url, args.model, key)
    def trace(run_id, root):
        return configured_trace(root / ".agent" / "traces" / (run_id + ".jsonl"), secrets=(key,))
    agent = create_agent(client, settings=settings, trace_factory=trace)
    def activity(event):
        kind = event["kind"]
        if kind == "model_requested":
            print(f"Model turn {event['turn']} ({event['tool_choice']})", file=sys.stderr, flush=True)
        elif kind == "tool_requested":
            print("Calling " + event["name"], file=sys.stderr, flush=True)
        elif kind == "tool_result":
            print(event["name"] + ": " + event["status"], file=sys.stderr, flush=True)
        elif kind == "completion_review":
            print(f"Checking completion (model turn {event['turn']})", file=sys.stderr, flush=True)
        elif kind == "completion_rejected":
            print("Completion check requires further work; continuing.", file=sys.stderr, flush=True)
    try:
        result = agent.run(query, workspace=workspace, skill_id=args.skill,
                           on_text=(lambda text: print(text, end="", flush=True)) if args.stream else None,
                           on_event=activity if args.stream else None)
    finally:
        client.close()
    if args.stream:
        print()
    elif result.answer:
        print(result.answer)
    for item in result.artifacts:
        print("File: " + str(workspace / item.path))
    print(f"Status: {result.status}; model turns: {result.model_turns}", file=sys.stderr)
    if result.reason and result.status != "completed":
        print(result.reason, file=sys.stderr)
    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.status == "completed" else 130 if result.status == "stopped" else 1
