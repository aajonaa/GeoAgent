"""Private operator-managed, account-specific knowledge capacity overrides."""
import json
import os
from pathlib import Path

DEFAULTS = {"max_documents": 100, "max_pdf_imports": 100}


def account_limits(owner):
    if not isinstance(owner, str) or not owner or len(owner) > 256:
        raise ValueError("Authenticated account required for knowledge limits")
    path = Path(os.environ.get("GEOTOOL_KNOWLEDGE_LIMITS_FILE",
                str(Path.home() / ".config/geoagent/knowledge-account-limits.json")))
    try:
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise ValueError("Knowledge capacity configuration must be private")
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return dict(DEFAULTS)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ValueError("Knowledge capacity configuration is unavailable") from None
    if (not isinstance(record, dict) or record.get("format") != "knowledge-account-limits-v1"
            or not isinstance(record.get("accounts"), dict)):
        raise ValueError("Invalid knowledge capacity configuration")
    override = record["accounts"].get(owner, {})
    if not isinstance(override, dict) or set(override) - set(DEFAULTS):
        raise ValueError("Invalid account knowledge capacity")
    result = {**DEFAULTS, **override}
    bounds = {"max_documents": 500000, "max_pdf_imports": 100000}
    if any(type(value) is not int or not 1 <= value <= bounds[key] for key, value in result.items()):
        raise ValueError("Knowledge capacities must be positive bounded integers")
    return result
