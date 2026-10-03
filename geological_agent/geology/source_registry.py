"""Register canonical source functions as ordinary native runtime tools.

The catalog owns argument/result schemas and source entry points. This module
does not implement scientific algorithms, parse action JSON or use retired
execution adapters. Workspace path preparation is an execution-runtime concern.
"""
from copy import deepcopy
from dataclasses import asdict
import importlib
from pathlib import Path
import re
import shutil
import uuid

from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, ROOT
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from ..skills import Skill, SkillSummary
from ..tools import Tool, ToolDefinition, ToolFailure, ToolOutput, artifact


READY = "source_revised_unverified"
ENTRY_MODULES = {
    "legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools",
    "legacy.ToolsAgent.ToolsFuns.Geoscience.geoscience_common",
    "legacy.ToolsAgent.ToolsFuns.GeoEval.runtime",
    "legacy.ToolsAgent.ToolsFuns.Geo.geoscienceTools",
}
# Declarative source semantics, not a planner or a tool-name heuristic.
# These operations query reference catalog records; model-authored rows cannot
# establish facts about the external catalog. Other tools may freely compute
# on generated inputs. Keep these declarations beside source registration.
REFERENCE_DATA_INPUTS = {
    "MineralResourcesSearchDeposits": ("dataset_path",),
    "MineralResourcesGetDeposit": ("dataset_path",),
    "MineralResourcesCountrySummary": ("dataset_path",),
    "MineralResourcesRankCommodityCountries": ("dataset_path",),
}

EXISTING_SKILLS = {"earthquake-energy-estimation": "earthquake_energy",
                   "geodesic-coordinate-analysis": "geodesic_coordinate_analysis"}


def source_tools():
    return {item["id"]: item for item in catalog()["tools"]}


def native_name(spec):
    return spec["function_definition"]["function"]["name"]


def _artifacts(output, ctx):
    if output is None or not output.exists():
        return ()
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(output):
                raise ToolFailure("invalid_output_path", "Source output escaped its task directory")
            files.append(artifact(path, ctx))
    return tuple(files)


def _handler(spec):
    entry = spec["source_interface"]["entrypoint"]
    module_name, function_name = entry["callable"].split(":")
    if module_name not in ENTRY_MODULES:
        raise ValueError("Unreviewed source module: " + module_name)

    def execute(args, ctx):
        ctx.check()
        params = deepcopy(args)
        remapping = {}
        scratch = None
        output = None
        try:
            for key in spec["source_interface"].get("path_fields", []):
                if key not in params:
                    continue
                original_value = params[key]
                values = original_value if isinstance(original_value, list) else [original_value]
                prepared = []
                for value in values:
                    original = ctx.path(value)
                    if key == "dir_path":
                        if not original.is_dir():
                            raise ToolFailure("missing_input", "Input directory not found: " + value, retryable=True)
                        if any(not child.resolve().is_relative_to(ctx.workspace.resolve()) for child in original.rglob("*")):
                            raise ToolFailure("invalid_path", "Input directory contains an external link")
                        prepared.append(str(original))
                        continue
                    if not original.is_file():
                        raise ToolFailure("missing_input", "Input file not found: " + value, retryable=True)
                    if scratch is None:
                        scratch = ctx.path(".agent/source-inputs/" + uuid.uuid4().hex)
                        scratch.mkdir(parents=True)
                    target = scratch / str(len(remapping)) / original.name
                    target.parent.mkdir()
                    shutil.copyfile(original, target)
                    remapping[str(target)] = original.relative_to(ctx.workspace.resolve()).as_posix()
                    prepared.append(str(target))
                params[key] = prepared if isinstance(original_value, list) else prepared[0]
            kwargs = dict(entry.get("bound_arguments", {}))
            kwargs[entry["argument_parameter"]] = params
            if entry.get("output_directory_parameter"):
                output = ctx.path("results/" + uuid.uuid4().hex)
                kwargs[entry["output_directory_parameter"]] = output
            function = getattr(importlib.import_module(module_name), function_name)
            result = function(**kwargs)
            ctx.check()

            def relative(value):
                if isinstance(value, str):
                    if value in remapping:
                        return remapping[value]
                    # Only path-valued strings under this workspace change.
                    # Other strings retain the source function's exact value.
                    if value.startswith(str(ctx.workspace.resolve())):
                        path = Path(value).resolve()
                        if path.is_relative_to(ctx.workspace.resolve()):
                            return path.relative_to(ctx.workspace.resolve()).as_posix()
                    return value
                if isinstance(value, list):
                    return [relative(item) for item in value]
                if isinstance(value, dict):
                    return {key: relative(item) for key, item in value.items()}
                return value

            return ToolOutput(relative(result), _artifacts(output, ctx))
        except ToolFailure:
            raise
        except ScientificToolError as exc:
            raise ToolFailure(exc.code, str(exc), retryable=exc.retryable,
                              artifacts=_artifacts(output, ctx)) from exc
        except ModuleNotFoundError as exc:
            raise ToolFailure("missing_dependency", "Install the professional dependency set; missing module: " + str(exc.name)) from exc
        except Exception as exc:
            raise ToolFailure("professional_tool_error", f"{type(exc).__name__}: {exc}",
                              retryable=True, artifacts=_artifacts(output, ctx)) from exc
        finally:
            if scratch is not None:
                # A generated directory resolved under this task, never a user path.
                if not scratch.resolve().is_relative_to(ctx.workspace.resolve() / ".agent/source-inputs"):
                    raise ToolFailure("invalid_path", "Refusing to remove an unexpected snapshot directory")
                shutil.rmtree(scratch)
    return execute


def register(registry):
    registered = {}
    for source_id, spec in source_tools().items():
        if spec.get("source_interface", {}).get("status") != READY:
            continue
        name = native_name(spec)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("Invalid native function name: " + name)
        usage = "Use for the stated scientific operation, with the declared inputs and units."
        if spec["source_interface"].get("path_fields"):
            usage += " Input paths must be task-relative; generated files are returned as artifacts."
        limitations = spec.get("limitations") or []
        if limitations:
            usage += " Limitations: " + "; ".join(map(str, limitations))
        registry.register(Tool(ToolDefinition(name, spec["description"], usage,
                               deepcopy(spec["input_schema"]), deepcopy(spec["output_schema"])),
                               _handler(spec), pure=not spec["source_interface"].get("path_fields"),
                               input_paths=tuple(spec["source_interface"].get("path_fields", [])),
                               reference_paths=REFERENCE_DATA_INPUTS.get(source_id, ())))
        registered[source_id] = name
    return registered


def load_source_skills(loader, registered):
    """Keep existing public IDs; discover blocked assets without advertising execution."""
    tools = source_tools()
    loader.source_statuses = {}
    loader.unavailable_skills = []
    for spec in catalog()["skills"]:
        skill_id = EXISTING_SKILLS.get(spec["id"], spec["id"].replace("-", "_"))
        references = spec.get("tool_references", [])
        available = tuple(dict.fromkeys(registered[name] for name in references if name in registered))
        blocked = [{"name": name, "reason": tools[name].get("source_interface", {}).get("reason", "No callable source interface")}
                   for name in references if name not in registered]
        loader.source_statuses[skill_id] = {"source_id": spec["id"], "unavailable_tools": blocked}
        summary = SkillSummary(skill_id, spec["name"], spec["description"], spec["description"])
        if not available:
            loader.unavailable_skills.append(asdict(summary))
            continue
        if spec["id"] in EXISTING_SKILLS:
            continue
        document = ROOT / spec["skill_file"]
        body = document.read_text(encoding="utf-8").split("---", 2)[-1].strip()
        notice = ("\nNative tool names available in this skill: " + ", ".join(available) +
                  ". Call them directly after disclosure. Unavailable references are not callable: " +
                  "; ".join(item["name"] + ": " + item["reason"] for item in blocked) + ".\n")
        loader.registry.register(Skill(summary, (), body + notice,
            ("Choose only operations required by the task; never fabricate unavailable data or results.",
             "Independent operations may share one response. No files or Python are needed unless the task requires them."),
            available, ("Observed results with units, provenance and limitations",)))
    return loader


def find_unavailable(loader, query):
    words = (query or "").casefold().split()
    return [row for row in loader.unavailable_skills if not words or
            any(word in " ".join(row.values()).casefold() for word in words)]
