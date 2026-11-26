"""Reproduce only the approved 27-tool/5-Skill registration metadata repair.

No algorithms, dependency pins, scientific schemas or acceptance states change.
The older pending-kernel generators do not generate these 27 tools or 5 Skills.
"""
from copy import deepcopy
import json
from pathlib import Path
import re

GROUP = Path(__file__).resolve().parent
ROOT = GROUP.parents[4]


def normalize(catalog, examples, documents):
    result = deepcopy(catalog)
    if len(result["tools"]) != 27 or len(result["skills"]) != 5:
        raise ValueError("This repair is restricted to the reviewed 27 tools and 5 Skills")
    ids = {tool["id"] for tool in result["tools"]}
    if len(ids) != 27 or ids != set(examples):
        raise ValueError("Independent examples must match the exact tool set")
    for tool in result["tools"]:
        entry = tool["source_interface"]["entrypoint"]
        if entry["module"] != "geological_agent.geology.expansion501_spatial":
            raise ValueError("Unexpected source module")
        if entry["callable"] != entry["module"] + ":" + entry["function"]:
            raise ValueError("Source binding is inconsistent")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", tool["id"]):
            raise ValueError("Invalid declared native English tool name")
        tool["example_arguments"] = deepcopy(examples[tool["id"]]["input"])
        tool["function_definition"] = {
            "type": "function", "function": {
                "name": tool["id"], "description": tool["description"],
                "parameters": deepcopy(tool["input_schema"]),
            },
        }
    revised_documents = {}
    for skill in result["skills"]:
        relative = "catalog/skills/" + skill["id"] + "/SKILL.md"
        if skill["metadata"]["canonical_skill_file"] != relative:
            raise ValueError("Unexpected canonical Skill path")
        skill["skill_file"] = relative
        text = documents[relative]
        normalized = skill["id"].replace("-", "_")
        matches = re.findall(r"^id: ([^\r\n]+)$", text, flags=re.MULTILINE)
        if matches != [skill["id"]] and matches != [normalized]:
            raise ValueError("Unexpected frontmatter ID: " + relative)
        revised_documents[relative] = re.sub(
            r"^id: [^\r\n]+$", "id: " + normalized, text, count=1, flags=re.MULTILINE)
    return result, revised_documents


def main():
    catalog_path = GROUP / "catalog-additions.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    examples = json.loads((GROUP / "examples-additions.json").read_text(encoding="utf-8"))
    documents = {skill["metadata"]["canonical_skill_file"]:
                 (ROOT / skill["metadata"]["canonical_skill_file"]).read_bytes().decode("utf-8")
                 for skill in catalog["skills"]}
    result, revised = normalize(catalog, examples, documents)
    catalog_path.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    for relative, text in revised.items():
        (ROOT / relative).write_bytes(text.encode("utf-8"))
    print(json.dumps({"tools": 27, "skills": 5, "scope": "registration_metadata_only", "science_executed": False}))


if __name__ == "__main__":
    main()
