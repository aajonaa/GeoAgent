"""Original XML unit binding; all values here are explicitly synthetic."""
import copy
import hashlib
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from collection_acceptance.hydro_data_opt_fixtures import WATERML2
from geological_agent.geology.collection_hydro_data_opt import bom_waterml_observations
from geological_agent.geology.collection_vendor.hydro_data_opt import bom_waterml
from legacy.ToolsAgent.ToolsFuns.GeoEval.scientific_tools import ScientificToolError

NS = '{http://www.opengis.net/waterml/2.0}'
UNITS = ['m3/s', 'ML/day', 'mm/day', 'mm', 'm', 'degC', 'K', 'dimensionless']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def make_xml(unit='m3/s', points=False):
    root = ET.fromstring(WATERML2)
    next(root.iter(NS + 'uom')).set('code', unit)
    if points:
        for row in root.iter(NS + 'MeasurementTVP'):
            metadata = ET.SubElement(row, NS + 'metadata')
            content = ET.SubElement(metadata, NS + 'TVPMeasurementMetadata')
            ET.SubElement(content, NS + 'uom', {'code': unit})
    return root


def write_xml(tmp_path, root):
    path = tmp_path / 'synthetic-waterml.xml'
    path.write_text(ET.tostring(root, encoding='unicode'), encoding='utf-8')
    return path


def assert_result(result, unit):
    assert result['values'] == [4.0, 8.0]
    assert result['times'] == ['2020-01-01T00:00:00Z', '2020-01-02T00:00:00Z']
    assert result['quality_codes'] == [-1, -1]
    assert result['station_id'] == 'urn:synthetic:SYN001'
    assert result['property'] == 'SYNTHETIC discharge'
    assert result['generated_at'] == '2020-01-04T00:00:00Z'
    assert result['count'] == 2
    assert result['units']['values'] == unit
    assert result['units']['times'] == 'ISO 8601 UTC'
    assert result['provenance']['tool'] == 'EarthHydroBomWaterMLObservations'
    assert result['provenance']['output_sha256'] == {}
    assert result['artifacts'] == []


@pytest.mark.parametrize('unit', UNITS)
@pytest.mark.parametrize('mode', ['object', 'json', 'keyword'])
def test_literal_units_values_times_and_source_are_preserved(tmp_path, unit, mode):
    path = write_xml(tmp_path, make_xml(unit))
    before = sha(path)
    upstream = Path(bom_waterml.__file__)
    upstream_before = sha(upstream)
    args = {'input_file': str(path), 'unit': unit}
    original_args = copy.deepcopy(args)
    if mode == 'keyword':
        result = bom_waterml_observations(args=args)
    else:
        result = bom_waterml_observations(json.dumps(args) if mode == 'json' else args)
    assert_result(result, unit)
    assert args == original_args and sha(path) == before
    assert sha(upstream) == upstream_before
    actual = next(iter(bom_waterml.BomWater().parse_data(SimpleNamespace(text=path.read_text(encoding='utf-8')), stations=None).values()))
    parsed_unit = actual.attrs['units']
    assert parsed_unit == unit.rsplit('/', 1)[-1]
    assert result['values'] == actual[actual.attrs['property'] + ' [' + parsed_unit + ']'].values.tolist()


@pytest.mark.parametrize('unit', ['m3/s', 'ML/day', 'mm/day'])
def test_matching_per_point_units_are_not_converted(tmp_path, unit):
    path = write_xml(tmp_path, make_xml(unit, points=True))
    before = sha(path)
    result = bom_waterml_observations({'input_file': str(path), 'unit': unit})
    assert_result(result, unit)
    assert sha(path) == before


BAD_CASES = ['wrong_request', 'missing_default_block', 'duplicate_default_block', 'missing_default_unit', 'missing_default_code', 'empty_default_code', 'duplicate_default_unit', 'conflicting_default_unit', 'conflicting_point_unit', 'duplicate_point_unit', 'missing_point_code', 'unit_outside_point_metadata', 'unit_outside_timeseries', 'duplicate_point_metadata', 'two_timeseries']


def invalid_xml(case):
    root = make_xml(points=True)
    series = next(root.iter(NS + 'MeasurementTimeseries'))
    default = series.find(NS + 'defaultPointMetadata')
    container = default.find(NS + 'DefaultTVPMeasurementMetadata')
    uom = container.find(NS + 'uom')
    row = next(root.iter(NS + 'MeasurementTVP'))
    point_metadata = row.find(NS + 'metadata')
    point_uom = next(point_metadata.iter(NS + 'uom'))
    requested = 'm3/s'
    if case == 'wrong_request':
        requested = 'mm'
    elif case == 'missing_default_block':
        series.remove(default)
    elif case == 'duplicate_default_block':
        series.append(copy.deepcopy(default))
    elif case == 'missing_default_unit':
        container.remove(uom)
    elif case == 'missing_default_code':
        uom.attrib.pop('code')
    elif case == 'empty_default_code':
        uom.set('code', '')
    elif case == 'duplicate_default_unit':
        container.append(copy.deepcopy(uom))
    elif case == 'conflicting_default_unit':
        ET.SubElement(container, NS + 'uom', {'code': 'mm'})
    elif case == 'conflicting_point_unit':
        point_uom.set('code', 'mm')
    elif case == 'duplicate_point_unit':
        point_metadata[0].append(copy.deepcopy(point_uom))
    elif case == 'missing_point_code':
        point_uom.attrib.pop('code')
    elif case == 'unit_outside_point_metadata':
        ET.SubElement(row, NS + 'uom', {'code': 'm3/s'})
    elif case == 'unit_outside_timeseries':
        ET.SubElement(root, NS + 'uom', {'code': 'm3/s'})
    elif case == 'duplicate_point_metadata':
        row.append(copy.deepcopy(point_metadata))
    elif case == 'two_timeseries':
        next(root.iter('{http://www.opengis.net/om/2.0}result')).append(copy.deepcopy(series))
    else:
        raise AssertionError(case)
    return root, requested


@pytest.mark.parametrize('case', BAD_CASES)
def test_inconsistent_missing_or_ambiguous_units_fail_without_changing_input(tmp_path, case):
    root, requested = invalid_xml(case)
    path = write_xml(tmp_path, root)
    before = sha(path)
    errors = []
    for _ in range(2):
        with pytest.raises(ScientificToolError) as failure:
            bom_waterml_observations({'input_file': str(path), 'unit': requested})
        assert failure.value.code == ('invalid_arguments' if case == 'wrong_request' else 'invalid_file')
        assert not failure.value.retryable
        errors.append((failure.value.code, str(failure.value)))
        assert sha(path) == before
    assert errors[0] == errors[1]


@pytest.fixture(scope='module')
def registry():
    from geological_agent.bootstrap import build_registry
    return build_registry()[0]


@pytest.mark.parametrize('mismatch', [False, True])
def test_native_runtime_preserves_units_and_rejects_mismatch(tmp_path, registry, mismatch):
    from geological_agent.contracts import ToolCall
    from geological_agent.settings import Settings
    from geological_agent.tools import ToolExecutionContext, ToolExecutor
    path = write_xml(tmp_path, make_xml(points=True))
    before = sha(path)
    name = 'EarthHydroBomWaterMLObservations'
    args = {'input_file': path.name, 'unit': 'mm' if mismatch else 'm3/s'}
    context = ToolExecutionContext('waterml-unit-acceptance', tmp_path, (name,), Settings(), Event())
    result = ToolExecutor(registry).execute(ToolCall('synthetic-waterml-call', name, args), context)
    assert sha(path) == before and not result.artifacts
    if mismatch:
        assert result.status == 'error'
        error_code = result.error.get('code') if isinstance(result.error, dict) else getattr(result.error, 'code', None)
        assert error_code == 'invalid_arguments'
    else:
        assert result.status == 'ok', result.error
        assert_result(result.data, 'm3/s')

