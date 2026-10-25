"""Summarize research proposals without adding them to the live tool count."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DELIVERY = ROOT / "catalog/source_delivery/github-expansion500-20261025"
STATUS = "research_only_not_integrated_not_counted"
INVENTORIES = {
    "geophysics": "groups/geophysics/research-inventory.json",
    "geology": "groups/geology/candidate-inventory.json",
    "remote": "groups/remote/inventory.json",
    "spatial": "groups/spatial/research-inventory.json",
}


def main():
    catalog = json.loads((ROOT / "catalog/registry.json").read_text(encoding="utf-8"))
    active_ids = {row["id"] for row in catalog["tools"]}
    seen = set()
    groups = {}
    entries = []
    callable_owners = {}
    for group, relative in INVENTORIES.items():
        path = DELIVERY / relative
        raw = path.read_bytes()
        document = json.loads(raw)
        rows = document.get("operations", document.get("candidates"))
        if not isinstance(rows, list) or not rows:
            raise ValueError("Missing candidate rows: " + relative)
        for row in rows:
            identifier = row.get("proposed_tool_id") or row.get("tool_id") or row.get("id") or row.get("candidate_id")
            if not isinstance(identifier, str) or not identifier or identifier in seen or identifier in active_ids:
                raise ValueError("Missing, repeated, or already active candidate ID: " + str(identifier))
            if row.get("status") != STATUS:
                raise ValueError("Candidate must not claim implementation or acceptance: " + identifier)
            seen.add(identifier)
            call = row.get("upstream_callable")
            if isinstance(call, str):
                callable_owners.setdefault(call, []).append(identifier)
            entries.append({"id":identifier, "group":group, "status":STATUS})
        groups[group] = {"candidates":len(rows), "inventory":relative,
                         "sha256":hashlib.sha256(raw).hexdigest()}
    target = 501
    count = len(entries)
    summary = {
        "date":"2026-10-25", "state":"research_inventory_not_integrated",
        "deployed_source_commit":"7466cfa5f321cc7b15f9609e8e160791fa7b23fd",
        "active_professional_operations":len(active_ids), "active_skills":len(catalog["skills"]),
        "research_candidates":count, "additional_integrated_from_research":0,
        "additional_accepted_from_research":0, "target_minimum_professional_operations":target,
        "accepted_additions_still_required":max(0, target-len(active_ids)),
        "hypothetical_total_if_every_candidate_passes":len(active_ids)+count,
        "further_candidates_required_even_if_all_pass":max(0, target-len(active_ids)-count),
        "hypothetical_total_is_not_a_release_count":True,
        "groups":groups, "entries":entries,
        "repeated_exact_callables_for_manual_review":{key:value for key,value in callable_owners.items() if len(value)>1},
        "validation_scope":"Unique proposed IDs, no ID collision with deployed registry, research-only status, and source-inventory hashes. Not semantic or numerical acceptance.",
        "remaining_gates":["Cross-group scientific distinctness and source/license review",
                           "Pinned private CPU dependencies and bounded AI-lab schemas",
                           "Named adapters, independent numerical oracles and negative tests",
                           "Native ToolExecutor and model-workflow acceptance before release"],
        "gpu_used":False, "production_changed_by_research":False,
    }
    with (DELIVERY / "SUMMARY.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    lines = ["# Further professional-tool research", "", "Research only. No proposals in this directory are registered or counted as active tools.", "",
             f"Current deployed professional operations: **{len(active_ids)}**. Current Skills: **{len(catalog['skills'])}**.",
             f"This inventory: **{count} research candidates**, with **0 newly implemented or accepted**.", "",
             "| Group | Candidates | Inventory |", "| --- | ---: | --- |"]
    for group, item in groups.items():
        lines.append(f"| {group} | {item['candidates']} | [{group}]({item['inventory']}) |")
    lines.extend(["", f"To exceed 500 professional operations requires **{summary['accepted_additions_still_required']} further accepted operations**.",
                  f"Even if all listed candidates pass, the hypothetical total is **{len(active_ids)+count}**, not an achieved release count.",
                  f"Another **{summary['further_candidates_required_even_if_all_pass']}** distinct candidates would still be needed under that optimistic assumption.", "",
                  "## Priority", "", "Prioritize SAR calibration/change analysis, mineral characterization and XRD, geophysical survey interpretation, and terrain/point-cloud analysis.",
                  "Keep low-level numeric or signal primitives under review until their domain workflow and distinction from existing tools are clear.", "",
                  "Each group retains its primary-source links, provenance, interface proposal and unresolved risks. Source review is not numerical validation.",
                  "The summary checks IDs and research status only; scientific deduplication, dependency compatibility, licensing and real execution remain separate gates.",
                  "No failed upstream algorithm, alias, research proposal or untested wrapper may increase the deployed count.", ""])
    with (DELIVERY / "README.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({key:summary[key] for key in ("active_professional_operations", "research_candidates",
                     "accepted_additions_still_required", "hypothetical_total_if_every_candidate_passes",
                     "further_candidates_required_even_if_all_pass")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
