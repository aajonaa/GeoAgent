"""Runtime helpers for SciToolAgent-style workflow tools."""

from __future__ import annotations

import importlib
import json
from typing import Iterable, List, Mapping, TypedDict


class WorkflowToolSpec(TypedDict):
    name: str
    category: str
    problem_type: str
    function: str
    workflow: str
    common_tools: List[str]
    import_modules: List[str]
    input: str
    output: str
    source: str


def _parse_input(input_text: str) -> str:
    text = (input_text or "").strip()
    if not text:
        return "(empty)"
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, dict):
        return "; ".join(f"{key}={value}" for key, value in parsed.items())
    return str(parsed)


def _module_status(modules: Iterable[str]) -> str:
    lines: list[str] = []
    for module in modules:
        module = module.strip()
        if not module:
            continue
        candidates = [part.strip() for part in module.split("|") if part.strip()]
        detected = ""
        for candidate in candidates:
            try:
                importlib.import_module(candidate)
                detected = candidate
                break
            except ImportError:
                continue
        display = candidates[0] if candidates else module
        if detected:
            lines.append(f"- {display}: detected as `{detected}`")
        else:
            lines.append(f"- {display}: not detected in current Python environment")
    return "\n".join(lines) if lines else "- No Python module check configured."


def run_workflow_tool(spec: WorkflowToolSpec, input_text: str) -> str:
    user_input = _parse_input(input_text)
    common_tools = "、".join(spec.get("common_tools", [])) or "未指定"
    module_status = _module_status(spec.get("import_modules", []))
    return "\n\n".join(
        [
            f"## {spec['name']}",
            f"**工具分类**：{spec['problem_type']}",
            f"**用途**：{spec['function']}",
            f"**标准流程**：{spec['workflow']}",
            f"**常用工具/库**：{common_tools}",
            f"**输入**：{user_input}",
            f"**输出**：{spec['output']}",
            f"**本地依赖检测**：\n{module_status}",
            (
                "**执行状态**：该工具已按照 SciToolAgent 的工具函数入口方式注册，可参与工具选择与工具链规划。"
                "当前实现提供基础工作流封装、参数承接和依赖检测；涉及真实业务数据处理时，"
                "请提供对应数据文件或在环境中安装所需第三方库。"
            ),
        ]
    )


def build_kg_rows(specs: Iterable[WorkflowToolSpec]) -> List[dict]:
    rows = []
    for spec in specs:
        common_tools = "、".join(spec.get("common_tools", []))
        rows.append(
            {
                "Name": spec["name"],
                "Category": spec["category"],
                "Function": (
                    f"{spec['function']} 处理流程：{spec['workflow']} "
                    f"常用工具：{common_tools}。问题类型：{spec['problem_type']}。"
                ),
                "Input": spec["input"],
                "Output": spec["output"],
                "Source": spec["source"],
                "Safety": "Yes",
                "Next": ",".join(spec.get("next_tools", [])),
            }
        )
    return rows


def tool_names(specs: Iterable[Mapping[str, object]]) -> List[str]:
    return [str(spec["name"]) for spec in specs]
