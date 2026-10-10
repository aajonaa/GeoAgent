"""Native source merge acceptance. All datasets are synthetic and labeled."""
import copy
import json
from pathlib import Path
from threading import Event

import pytest
from jsonschema import Draft202012Validator
from geological_agent.bootstrap import create_agent
from geological_agent.contracts import ToolCall
from geological_agent.tools import ToolExecutionContext
from legacy.ToolsAgent.ToolsFuns.GeoEval import native_recovery as native
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError
from legacy.ToolsAgent.ToolsFuns.source_contracts import catalog, definition
from source_asset_checks.recovered_cases import create, oracle, usgs_fixture
from source_asset_checks.run import invoke_source, check_assets
from geotool.domain_worker import run as transport

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = json.loads((ROOT / "catalog/source_delivery/examples.json").read_text(encoding="utf-8"))

@pytest.fixture
def inputs(tmp_path, monkeypatch):
    create(tmp_path)
    monkeypatch.setattr(native, "_usgs_response", usgs_fixture)
    return tmp_path

def params(name, root, **changes):
    value = copy.deepcopy(EXAMPLES[name])
    value.update(changes)
    for key in definition(name)["source_interface"]["path_fields"]:
        if key in value:
            value[key] = str(root / value[key])
    return value

@pytest.mark.parametrize("name", native.RECOVERED)
@pytest.mark.parametrize("mode", ["object", "json", "transport"])
def test_independent_calls_have_exact_contracts_and_content(inputs, name, mode):
    spec = definition(name)
    Draft202012Validator.check_schema(spec["input_schema"])
    Draft202012Validator.check_schema(spec["output_schema"])
    assert spec["function_definition"]["function"]["parameters"] == spec["input_schema"]
    assert spec["metadata"]["scientific_contract"]["data_mode"] != "benchmark_answer_lookup"
    output = inputs / "outputs" / mode
    output.mkdir(parents=True)
    if mode == "transport":
        response = transport({"tool_id": name, "input": copy.deepcopy(EXAMPLES[name]), "workspace": str(inputs)})
    else:
        response = invoke_source(spec, EXAMPLES[name], inputs, output, serialized=(mode == "json"))
    Draft202012Validator(spec["output_schema"]).validate(response["result"])
    oracle(name, response, inputs)

def test_inventory_archive_is_disjoint_and_complete():
    current = catalog()
    archive = json.loads((ROOT / "catalog/archive/placeholders-20261004.json").read_text(encoding="utf-8"))
    active = {row["id"] for row in current["tools"]}
    inactive = {row["id"] for row in archive["tools"]}
    assert len(active) == 116 and len(inactive) == 62 and not active & inactive
    assert set(native.RECOVERED) <= active
    assert all(row["source_interface"]["status"] == "source_revised_unverified" for row in current["tools"])
    checks = check_assets(current, {row["id"]: row for row in current["tools"]})
    assert len(checks) == 34 and all(row["status"] == "passed" for row in checks), checks

@pytest.mark.parametrize("name", native.RECOVERED)
def test_unknown_arguments_never_reach_algorithms(inputs, name):
    with pytest.raises(ScientificToolError) as exc:
        native.run(name, params(name, inputs, unexpected=True), output_dir=inputs / "out")
    assert exc.value.code == "invalid_arguments"

def test_no_implicit_or_guessed_data(inputs):
    name = "DeepEarthQueryLITHO1"
    value = params(name, inputs)
    del value["dataset_path"]
    with pytest.raises(ScientificToolError, match="dataset_path"):
        native.run(name, value)
    with pytest.raises(ScientificToolError) as exc:
        native.run(name, params(name, inputs, dataset_path="missing.csv"))
    assert exc.value.code == "missing_input"

@pytest.mark.parametrize("changes", [
    {"scalar": 2, "other_path": "assets/recovered-examples/green.tif"},
    {"scalar": None},
    {"operation": "divide", "scalar": 0},
])
def test_raster_operands_and_empty_output_rejected(inputs, changes):
    with pytest.raises(ScientificToolError):
        native.run("CCSRasterAlgebra", params("CCSRasterAlgebra", inputs, **changes), output_dir=inputs / "out")

def test_raster_alignment_and_dates_are_checked(inputs):
    import rasterio
    from rasterio.transform import from_origin
    with pytest.raises(ScientificToolError, match="same acquisition"):
        native.run("RemoteSensingNDTI", params("RemoteSensingNDTI", inputs, green_date="2020-01-02"), output_dir=inputs / "out")
    with rasterio.open(inputs / "assets/recovered-examples/green.tif", "r+") as data:
        data.transform = from_origin(1, 2, 1, 1)
    with pytest.raises(ScientificToolError, match="identical grids"):
        native.run("RemoteSensingNDTI", params("RemoteSensingNDTI", inputs), output_dir=inputs / "out")

def test_source_metadata_scale_applied(inputs):
    import rasterio
    with rasterio.open(inputs / "assets/recovered-examples/red.tif", "r+") as data:
        data.scales = (.1,)
        data.offsets = (1.,)
    out = native.run("CCSRasterAlgebra", params("CCSRasterAlgebra", inputs), output_dir=inputs / "out")
    assert out["data"]["mean"] == pytest.approx(3.5)

@pytest.mark.parametrize("query", [
    "SELECT * WHERE { SERVICE <https://example.invalid/> { ?s ?p ?o } }",
    "SELECT * FROM <file:///etc/passwd> WHERE { ?s ?p ?o }",
    "DELETE WHERE { ?s ?p ?o }",
    "ASK { ?s ?p ?o }",
])
def test_sparql_does_not_fetch_or_update(inputs, query):
    with pytest.raises(ScientificToolError):
        native.run("GeoBigDataExecuteGeoSPARQL", params("GeoBigDataExecuteGeoSPARQL", inputs, query=query))

def test_zero_capacity_has_no_invented_percentage(inputs):
    out = native.run("EnergyCapacityGrowth", params("EnergyCapacityGrowth", inputs, series="zero"))
    assert out["data"]["absolute_growth_mw"] == 10
    assert out["data"]["percentage_growth"] is None

def test_duplicate_model_keys_rejected(inputs):
    path = inputs / "assets/recovered-examples/nodes.csv"
    with path.open("a") as stream:
        stream.write("n1,0,0,99,999\n")
    with pytest.raises(ScientificToolError, match="Duplicate"):
        native.run("DeepEarthQueryLITHO1", params("DeepEarthQueryLITHO1", inputs))

def test_online_tool_is_not_pure_cached(inputs):
    agent = create_agent(object())
    name = "USGSEarthquakeCatalogFetch"
    assert agent.tools.get(name).pure is False
    context = ToolExecutionContext("network", inputs, (name,), agent.settings, Event())
    first = agent.executor.execute(ToolCall("fetch-1", name, EXAMPLES["USGS 地震数据获取"]), context)
    second = agent.executor.execute(ToolCall("fetch-2", name, EXAMPLES["USGS 地震数据获取"]), context)
    assert first.status == second.status == "ok"
    assert not first.cached and not second.cached
    assert first.data["data"]["output_path"] != second.data["data"]["output_path"]

def test_usgs_http_error_is_not_empty_success(monkeypatch):
    import requests
    class Response:
        status_code = 429
    monkeypatch.setattr(requests, "get", lambda *a, **kw: Response())
    with pytest.raises(ScientificToolError) as exc:
        native._usgs_response({})
    assert exc.value.code == "upstream_error" and exc.value.retryable

def test_usgs_limit_flag_is_explicit(inputs):
    out = native.run("USGS 地震数据获取", {"start": "2020-01-01", "end": "2020-01-03", "limit": 1}, output_dir=inputs / "out")
    assert out["data"]["count"] == 1 and out["data"]["possibly_limited"] is True
