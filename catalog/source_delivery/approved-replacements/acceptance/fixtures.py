"""Explicitly synthetic fixtures; never evidence of a real aquifer or flow record."""
import json
from pathlib import Path

def create(root):
    examples = json.loads(Path(__file__).with_name("examples.json").read_text())
    target = Path(root) / "assets/earth-collection/approved-functional-replacements/synthetic-examples.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump({"synthetic": True, "not_observed_data": True, "examples": examples}, stream, indent=2)
    return str(target)
