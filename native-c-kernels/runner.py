"""Fixed entrypoint: python runner.py TOOL_NAME, bounded JSON object on stdin."""
import json
import sys
from adapters import OPERATIONS, fail


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in OPERATIONS:
            fail("Exactly one fixed registered kernel name is required.")
        data = sys.stdin.buffer.read(262145)
        if len(data) > 262144:
            fail("Input exceeds the fixed 256 KiB bound.")
        try:
            args = data.decode("utf-8")
        except UnicodeDecodeError:
            fail("Input must be UTF-8 JSON.")
        result = OPERATIONS[sys.argv[1]](args=args)
        print(json.dumps({"status": "ok", "tool": sys.argv[1], "data": result}, allow_nan=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": {"code": getattr(exc, "code", "execution_error"), "message": str(exc), "retryable": False}}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

