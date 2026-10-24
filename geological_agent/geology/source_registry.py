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

import yaml

from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, ROOT
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from ..skills import Skill, SkillSummary
from ..tools import Tool, ToolDefinition, ToolFailure, ToolOutput, artifact


READY = "source_revised_unverified"
ENTRY_MODULES = {
    'geological_agent.geology.collection_hydro_cpu.adapters',
    "geological_agent.geology.native_cpu_kernels",
    "geological_agent.geology.collection_wflow43",
    "geological_agent.geology.collection_approved_replacements",
    "geological_agent.geology.collection_offline_originals.adapters",
    "geological_agent.geology.collection_offline_originals.pyglue_fixed.adapters",
    "legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools",
    "legacy.ToolsAgent.ToolsFuns.Geoscience.geoscience_common",
    "legacy.ToolsAgent.ToolsFuns.GeoEval.runtime",
    "legacy.ToolsAgent.ToolsFuns.GeoEval.native_recovery",
    "legacy.ToolsAgent.ToolsFuns.Geo.geoscienceTools",
    "geological_agent.geology.github_first_batch",
    "geological_agent.geology.earth_python_wave1",
    "geological_agent.geology.collection_spatial",
    "geological_agent.geology.collection_hydro_data_opt",
    "geological_agent.geology.collection_hydro_models",
    "geological_agent.geology.collection_groundwater_other",
    "geological_agent.geology.collection_weather_climate_seismic",
}
# Declarative source semantics, not a planner or a tool-name heuristic.
# These operations query reference catalog records; model-authored rows cannot
# establish facts about the external catalog. Other tools may freely compute
# on generated inputs. Keep these declarations beside source registration.
REFERENCE_DATA_INPUTS = {
    "DeepEarthQueryLITHO1": ("dataset_path",),
    "DeepEarthQuerySEMUCB": ("dataset_path",),
    "DeepEarthGetUSGSEvent": ("dataset_path",),
    "DeepEarthQueryUSGSCatalog": ("dataset_path",),
    "DeepEarthSampleEventModels": ("dataset_path",),
    "GeoBigDataExecuteGeoSPARQL": ("dataset_path",),
    "ClimateQueryDeepTime": ("dataset_path",),
    "ClimateQueryPresentMean": ("dataset_path",),
    "ClimateQueryFutureSSP": ("dataset_path",),
    "EnergyFacilityDistance": ("dataset_path",),
    "EnergyMineralSiteDistance": ("dataset_path",),
    "EnergyNearestFacility": ("dataset_path",),
    "EnergyNearestMineralSite": ("dataset_path", "facilities_path"),
    "EnergyCapacityValue": ("dataset_path",),
    "EnergyCapacityGrowth": ("dataset_path",),
    "EnergyCountryRenewableSummary": ("dataset_path",),
    "EnergyTransitionMetrics": ("dataset_path",),
    "EnergyRegionalOverlaySummary": ("dataset_path", "minerals_path"),
    "OceanMonthlyGridValue": ("dataset_path",),
    "OceanProfileValue": ("dataset_path",),
    "OceanVerticalProfileDifference": ("dataset_path",),
    "OceanCruiseQC": ("dataset_path",),
    "OceanStationDistance": ("dataset_path",),
    "OceanAnnualCarbonSummary": ("dataset_path",),
    "OceanRegionalMapSummary": ("dataset_path",),
    "OceanSurfaceDeepMatch": ("dataset_path", "deep_path"),
    "OceanProfileDeduplication": ("dataset_path",),
    "MineralResourcesSearchDeposits": ("dataset_path",),
    "MineralResourcesGetDeposit": ("dataset_path",),
    "MineralResourcesCountrySummary": ("dataset_path",),
    "MineralResourcesRankCommodityCountries": ("dataset_path",),
}

EXISTING_SKILLS = {"earthquake-energy-estimation": "earthquake_energy",
                   "geodesic-coordinate-analysis": "geodesic_coordinate_analysis",
                   "scientific-raster-analysis": "scientific_raster_analysis",
                   "map-color-digitization": "map_color_digitization",
                   "plot-curve-digitization": "plot_curve_digitization"}


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
        if spec["source_interface"].get("kind") == "native_scientific_workspace":
            # Already installed by the canonical module. Verify its contract;
            # do not wrap it, remap its arguments, or register a second handler.
            from ..scientific_imaging import SCHEMAS
            entry = spec["source_interface"]["entrypoint"]
            if (name not in SCHEMAS or entry != {
                    "callable": "geological_agent.scientific_imaging:operate",
                    "argument_parameter": "args", "bound_arguments": {"name": name},
                    "workspace_parameter": "workspace"}):
                raise ValueError("Unreviewed native scientific entrypoint: " + name)
            tool = registry.get(name)
            if (tool.definition.input_schema != spec["input_schema"] or
                    tool.definition.result_schema != spec["output_schema"] or
                    tool.definition.description != spec["description"] or
                    tool.input_paths != tuple(spec["source_interface"]["path_fields"])):
                raise ValueError("Native scientific asset contract drift: " + name)
            registered[source_id] = name
            continue
        usage = "Use for the stated scientific operation, with the declared inputs and units."
        if spec["source_interface"].get("path_fields"):
            usage += " Input paths must be task-relative; generated files are returned as artifacts."
        limitations = spec.get("limitations") or []
        if limitations:
            usage += " Limitations: " + "; ".join(map(str, limitations))
        registry.register(Tool(ToolDefinition(name, spec["description"], usage,
                               deepcopy(spec["input_schema"]), deepcopy(spec["output_schema"])),
                               _handler(spec), pure=spec["source_interface"].get("pure", not spec["source_interface"].get("path_fields") and not spec["source_interface"].get("network_required", False)),
                               input_paths=tuple(spec["source_interface"].get("path_fields", [])),
                               reference_paths=REFERENCE_DATA_INPUTS.get(source_id, ())))
        registered[source_id] = name
    return registered


def load_source_skills(loader, registered, *, runtime_registry=None):
    """Load every skill from the canonical catalog; preserve public skill IDs."""
    tools = source_tools()
    resolved = dict(registered)
    if runtime_registry is not None:
        # Basic file/image tools are dependencies, not duplicate scientific assets.
        for name in runtime_registry.names():
            if name not in tools:
                resolved.setdefault(name, name)
    loader.source_statuses = {}
    loader.unavailable_skills = []
    for spec in catalog()["skills"]:
        skill_id = EXISTING_SKILLS.get(spec["id"], spec["id"].replace("-", "_"))
        references = spec.get("tool_references", [])
        available = tuple(dict.fromkeys(resolved[name] for name in references if name in resolved))
        blocked = [{"name": name, "reason": tools.get(name, {}).get("source_interface", {}).get("reason", "No registered callable dependency")}
                   for name in references if name not in resolved]
        loader.source_statuses[skill_id] = {"source_id": spec["id"], "unavailable_tools": blocked}
        summary = SkillSummary(skill_id, spec["name"], spec["description"], spec["description"])
        if not available:
            loader.unavailable_skills.append(asdict(summary))
            continue
        document = (ROOT / spec["skill_file"]).resolve()
        if not document.is_relative_to((ROOT / "catalog/skills").resolve()):
            raise ValueError("Skill document must be in the canonical catalog")
        parts = document.read_text(encoding="utf-8").split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            raise ValueError("Missing skill front matter: " + spec["id"])
        metadata = yaml.safe_load(parts[1])
        body = parts[2].strip()
        if not isinstance(metadata, dict) or not body:
            raise ValueError("Invalid skill document: " + spec["id"])
        if metadata.get("id", skill_id) != skill_id:
            raise ValueError("Skill ID differs from catalog: " + spec["id"])
        summary = SkillSummary(skill_id, spec["name"], spec["description"],
                               metadata.get("when_to_use", spec["description"]))
        if "tools" in metadata:
            declared = tuple(metadata["tools"])
            expected = tuple(resolved.get(name, name) for name in references)
            if declared != expected:
                raise ValueError("Skill tool references differ from catalog: " + spec["id"])
            summary = SkillSummary(skill_id, metadata["name"], metadata["description"],
                                   metadata.get("when_to_use", metadata["description"]))
            constraints = tuple(metadata.get("constraints", []))
        else:
            body += ("\nNative tool names available in this skill: " + ", ".join(available) +
                     ". Call them directly after disclosure. Unavailable references are not callable: " +
                     "; ".join(item["name"] + ": " + item["reason"] for item in blocked) + ".\n")
            constraints = ("Choose only operations required by the task; never fabricate unavailable data or results.",
                           "Independent operations may share one response. No files or Python are needed unless the task requires them.")
        loader.registry.register(Skill(summary, tuple(metadata.get("required_inputs", [])), body,
            constraints, available, tuple(metadata.get("expected_outputs", ["Observed results with units, provenance and limitations"]))))
    return loader


def find_unavailable(loader, query):
    words = (query or "").casefold().split()
    return [row for row in loader.unavailable_skills if not words or
            any(word in " ".join(row.values()).casefold() for word in words)]
