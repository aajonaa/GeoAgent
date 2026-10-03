"""Authenticated, read-only views of the exact native runtime asset registry."""
from copy import deepcopy
from dataclasses import asdict
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path

from fastapi import Request
from jsonschema import Draft202012Validator

from ..bootstrap import build_registry
from ..geology.source_registry import EXISTING_SKILLS
from legacy.ToolsAgent.ToolsFuns.source_contracts import ROOT, catalog


NOTICE = ("接入状态来自当前运行时注册表，不代表科学结果已验收。"
          "所需数据、依赖环境和参数仍需在执行时检查；浏览目录不会执行工具或调用模型。")


def _strings(value):
    if isinstance(value, str):
        return [value]
    return [item for item in (value or []) if isinstance(item, str)] if isinstance(value, (list, tuple)) else []


class LibraryCatalog:
    def __init__(self, *, human_input=False):
        registry, loader, base_tools = build_registry(human_input=human_input)
        source = catalog()
        self.tools, self.skills = {}, {}
        native_to_source = {}
        registered = set(registry.names())
        for spec in source["tools"]:
            native = spec.get("function_definition", {}).get("function", {}).get("name") or spec["id"]
            definition = registry.get(native).definition if native in registered else None
            self.tools[spec["id"]] = self._tool(spec, definition)
            native_to_source[native] = spec["id"]
        for native in registry.names():
            if native not in native_to_source:
                definition = registry.get(native).definition
                self.tools[native] = self._tool(
                    {"id": native, "name": native, "category": "Runtime", "description": definition.description},
                    definition, scope="runtime",
                )
                native_to_source[native] = native
        runtime = {s.id: loader.load(s.id) for s in loader.registry.list()}
        for spec in source["skills"]:
            identifier = EXISTING_SKILLS.get(spec["id"], spec["id"].replace("-", "_"))
            actual = runtime.pop(identifier, None)
            self.skills[identifier] = self._skill(spec, identifier, actual, native_to_source)
        for identifier, actual in runtime.items():
            self.skills[identifier] = self._skill(
                {"id": identifier, "name": actual.summary.name,
                 "description": actual.summary.description,
                 "metadata": {"domain": {"primary": "Runtime"}}},
                identifier, actual, native_to_source, scope="runtime",
            )
        for skill in self.skills.values():
            for tool in skill["tools"]:
                if tool["id"] in self.tools:
                    self.tools[tool["id"]]["skills"].append({
                        "id": skill["id"], "name": skill["name"], "status": skill["status"],
                    })
        fingerprint = json.dumps({"tools": self.tools, "skills": self.skills},
                                 sort_keys=True, ensure_ascii=False).encode("utf-8")
        self.revision = hashlib.sha256(fingerprint).hexdigest()[:12]
        self.catalog_skill_count = len(source["skills"])
        self.catalog_tool_count = len(source["tools"])
        self.base_tools = tuple(base_tools)

    @staticmethod
    def _tool(spec, definition, *, scope="professional"):
        interface = spec.get("source_interface", {})
        inputs = deepcopy(definition.input_schema if definition else spec.get("input_schema", {}))
        outputs = deepcopy(definition.result_schema if definition else spec.get("output_schema", {}))
        inputs = inputs if isinstance(inputs, dict) else {}
        outputs = outputs if isinstance(outputs, dict) else {}
        example = deepcopy(spec.get("example_arguments"))
        if not isinstance(example, dict) or not definition or not Draft202012Validator(inputs).is_valid(example):
            example = None
        name = definition.name if definition else spec["id"]
        return {
            "id": spec["id"], "name": spec.get("name") or name, "native_name": name,
            "kind": "tools", "scope": scope,
            "description": definition.description if definition else spec.get("description", ""),
            "category": spec.get("category") or "Other",
            "tags": _strings(spec.get("tags")),
            "status": "registered" if definition else "blocked",
            "reason": "" if definition else interface.get("reason") or "尚未注册到当前运行时，不能直接调用。",
            "when_to_use": definition.when_to_use if definition else "",
            "input_schema": inputs, "output_schema": outputs,
            "limitations": _strings(spec.get("limitations")),
            "path_fields": _strings(interface.get("path_fields")),
            "version": spec.get("version") or "未声明",
            "validation": interface.get("validation") or "未提供独立验收标记",
            "example_arguments": example, "skills": [],
            "example_prompt": ("请使用 " + name + " 完成其专业计算。输入参数如下：\n"
                + json.dumps(example, ensure_ascii=False, indent=2)
                + "\n请说明结果、单位与方法限制。如需数据文件，请先确认文件存在；缺少信息时请询问，不要编造。")
                if example is not None else "",
        }

    def _skill(self, spec, identifier, actual, native_to_source, *, scope="professional"):
        refs = list(dict.fromkeys([
            *_strings(spec.get("tool_references")),
            *(native_to_source.get(n, n) for n in (actual.tool_names if actual else ())),
        ]))
        tools = [{"id": name, "name": self.tools.get(name, {}).get("name", name),
                  "status": self.tools.get(name, {}).get("status", "blocked"),
                  "reason": self.tools.get(name, {}).get("reason", "注册表中缺少此工具。")}
                 for name in refs]
        available = sum(row["status"] == "registered" for row in tools)
        status = "blocked" if not actual or not available else "registered" if available == len(tools) else "partial"
        workflow = spec.get("metadata", {}).get("workflow", {}).get("steps", [])
        inputs = list(actual.required_inputs) if actual else []
        outputs = list(actual.expected_outputs) if actual else []
        if not inputs:
            inputs = list(dict.fromkeys(item for step in workflow for item in _strings(step.get("inputs"))))
        if not outputs:
            outputs = list(dict.fromkeys(item for step in workflow for item in _strings(step.get("outputs"))))
        instructions = actual.instructions if actual else self._document(spec.get("skill_file", ""))
        prompts = []
        for example in spec.get("examples") or []:
            prompt = example if isinstance(example, str) else example.get("prompt") if isinstance(example, dict) else None
            if isinstance(prompt, str) and prompt.strip():
                prompts.append(prompt.strip())
        prompt = prompts[0] if prompts else ("请按照「" + (actual.summary.name if actual else spec["name"])
            + "」的方法帮助我完成下面的任务：\n任务目标：[请填写]\n输入参数或材料：[请填写]\n"
            "只选择任务需要的工具，说明结果与限制；缺少关键信息时先向我确认。")
        return {
            "id": identifier, "source_id": spec["id"], "kind": "skills", "scope": scope,
            "name": actual.summary.name if actual else spec["name"],
            "description": actual.summary.description if actual else spec.get("description", ""),
            "category": spec.get("metadata", {}).get("domain", {}).get("primary") or "Other",
            "tags": _strings(spec.get("applicability", {}).get("keywords")),
            "status": status,
            "reason": "" if status == "registered" else "部分关联工具尚未接入，请选择已接入的操作。" if status == "partial"
                else "此 Skill 尚未接入运行时，关联工具当前不能完成其流程。",
            "when_to_use": actual.summary.when_to_use if actual else spec.get("description", ""),
            "required_inputs": inputs, "expected_outputs": outputs,
            "constraints": list(actual.constraints) if actual else _strings(spec.get("method_notes")),
            "instructions": instructions,
            "document_kind": "运行时 Skill 说明" if actual else "登记文档（尚未接入）",
            "tools": tools, "tool_count": len(tools), "available_tool_count": available,
            "example_prompt": prompt if status != "blocked" else "",
        }

    @staticmethod
    def _document(relative):
        if not relative:
            return ""
        # No user-controlled filesystem paths. Do not expose source entrypoints,
        # server paths, installed-package locations, or account data.
        path = (ROOT / relative).resolve()
        allowed = (ROOT / "catalog" / "skills").resolve()
        if path.name != "SKILL.md" or not path.is_relative_to(allowed) or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8")
        parts = text.split("---", 2)
        return parts[2].strip() if len(parts) == 3 and not parts[0].strip() else text

    @staticmethod
    def _summary(row):
        keys = ("id", "name", "kind", "scope", "description", "category", "tags", "status", "reason",
                "native_name", "tool_count", "available_tool_count")
        item = {key: row[key] for key in keys if key in row}
        if row["kind"] == "skills":
            item["tool_preview"] = [tool["name"] for tool in row["tools"][:3]]
        return item

    def summary(self):
        return {
            "revision": self.revision, "release": os.environ.get("GEOTOOL_RELEASE", "local"),
            "notice": NOTICE,
            "counts": {"skills": len(self.skills), "tools": len(self.tools),
                       "professional_tools": self.catalog_tool_count,
                       "catalog_skills": self.catalog_skill_count,
                       "registered_tools": sum(t["status"] == "registered" for t in self.tools.values()),
                       "runtime_tools": sum(t["scope"] == "runtime" for t in self.tools.values())},
            "skills": [self._summary(row) for row in self.skills.values()],
            "tools": [self._summary(row) for row in self.tools.values()],
        }

    def detail(self, kind, identifier):
        rows = {"skills": self.skills, "tools": self.tools}.get(kind, {})
        if identifier not in rows:
            raise KeyError(identifier)
        return deepcopy(rows[identifier])


def install_library_routes(app, auth, *, human_input=False):
    @lru_cache(maxsize=1)
    def assets():
        return LibraryCatalog(human_input=human_input)

    @app.get("/api/library")
    def library_index(request: Request):
        auth(request)
        return assets().summary()

    @app.get("/api/library/{kind}/{identifier}")
    def library_detail(kind: str, identifier: str, request: Request):
        auth(request)
        return assets().detail(kind, identifier)
