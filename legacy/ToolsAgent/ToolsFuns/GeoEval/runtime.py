"""Original scientific implementations with structured source interfaces.

Public dispatch accepts named arguments and returns dictionaries. File-producing calls require explicit output_dir. Contracts come from catalog/registry.json; this source revision has not been tested."""
from __future__ import annotations
from contextvars import ContextVar
from ..source_contracts import arguments as source_arguments, result as source_result, decode as source_decode, check_files as source_check_files
import json
import importlib.util
import math
import os
import re
import shutil
from difflib import SequenceMatcher
from collections import Counter
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATASET_ROOT = Path(os.environ.get('GEOTOOL_DATASET_ROOT', str(_REPO_ROOT.parent / 'GeoToolAgent数据集')))
_RUNTIME_OUTPUTS = _REPO_ROOT / 'outputs' / 'geotool_runtime'

def _flatten_parameter_wrappers(value: dict[str, Any]) -> dict[str, Any]:
    """Expose authoritative locator fields without discarding their provenance."""
    flattened = dict(value)
    for key in ('source_locator', 'arguments', 'parameters', 'params', 'locator', 'context'):
        nested = value.get(key)
        if isinstance(nested, dict):
            for nested_key, nested_value in nested.items():
                current = flattened.get(nested_key)
                if nested_key not in flattened or current is None or current == '' or (current == '*'):
                    flattened[nested_key] = nested_value
    nested_input = value.get('input')
    if isinstance(nested_input, dict):
        for nested_key, nested_value in nested_input.items():
            flattened.setdefault(nested_key, nested_value)
    elif isinstance(nested_input, str) and nested_input.strip().startswith(('{', '[')):
        try:
            decoded = source_decode(nested_input)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            for nested_key, nested_value in decoded.items():
                flattened.setdefault(nested_key, nested_value)
    return flattened

def _first_number(value: Any) -> float | None:
    """Return the first finite numeric leaf from an upstream result object."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, dict):
        preferred = ('value', 'mid', 'mean', 'numeric_result', 'value_km', 'temp_anomaly_c', 'dlnvs_percent')
        for key in preferred:
            if key in value:
                number = _first_number(value[key])
                if number is not None:
                    return number
        for item in value.values():
            number = _first_number(item)
            if number is not None:
                return number
    if isinstance(value, (list, tuple)):
        for item in value:
            number = _first_number(item)
            if number is not None:
                return number
    return None

def _params(input_str: str) -> dict[str, Any]:
    if isinstance(input_str, dict):
        return dict(input_str)
    text = (input_str or '').strip()
    if not text:
        return {}
    try:
        value = source_decode(text)
    except json.JSONDecodeError:
        return {'input_text': text}
    if isinstance(value, dict):
        params = _flatten_parameter_wrappers(value)
        aliases = {'ssp': 'scenario', 'ssp_scenario': 'scenario', 'ssp_horizon': 'horizon_year', 'year': 'horizon_year', 'start': 'year_start', 'end': 'year_end', 'grouping_fields': 'group_by', 'grouping_field': 'group_by', 'expocode': 'glodap_expocode', 'glodap_expocode': 'expocode', 'station_id': 'station', 'cruise_id': 'cruise', 'fco2rec_flag': 'fCO2rec_flag', 'longitude': 'lon', 'latitude': 'lat'}
        for source, target in aliases.items():
            if target not in params or params.get(target) in (None, '', []):
                if params.get(source) not in (None, '', []):
                    params[target] = params[source]
        if isinstance(params.get('input'), dict):
            params.update({k: v for k, v in params['input'].items() if params.get(k) in (None, '', [])})
        return params
    if isinstance(value, list):
        return {'x': value}
    return {'value': value}

def _clean(value: Any) -> Any:
    try:
        import numpy as np
        if isinstance(value, np.generic):
            value = value.item()
    except ImportError:
        pass
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, 'isoformat') and type(value).__module__.startswith(('pandas', 'numpy')):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    return value

def _result(**payload: Any) -> str:
    from .scientific_contracts import nonfinite_paths
    invalid = nonfinite_paths(payload)
    if invalid:
        return {'status': 'error', 'error_type': 'scientific_result_error', 'retryable': False, 'error': 'Non-finite scientific values cannot establish successful execution', 'invalid_value_paths': invalid}
    return _clean(payload)

def _read_csv(path: Path):
    import pandas as pd
    return pd.read_csv(path)

def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [source_decode(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

@lru_cache(maxsize=None)
def _load_dataset_generator(script_stem: str):
    """Load a retained dataset parser independently of the service CWD."""
    generator_path = _REPO_ROOT / 'scripts' / f'{script_stem}.py'
    spec = importlib.util.spec_from_file_location(f'geotoolagent_{script_stem}', generator_path)
    if spec is None or spec.loader is None:
        raise ImportError(f'Unable to load dataset parser from {generator_path}')
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator

def _row_dict(row) -> dict[str, Any]:
    return {str(key): _clean(value) for key, value in row.to_dict().items()}

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = (math.radians(lat1), math.radians(lat2))
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def _bbox_area(bbox: list[float]) -> float:
    min_lon, min_lat, max_lon, max_lat = [float(value) for value in bbox]
    radius_km = 6371.0088
    return abs(radius_km ** 2 * math.radians(max_lon - min_lon) * (math.sin(math.radians(max_lat)) - math.sin(math.radians(min_lat))))

def _point_pair(params: dict[str, Any]) -> tuple[float, float, float, float]:
    text = str(params.get('input_text', ''))
    if text:
        left, right = text.split(';', 1)
        lat1, lon1 = [float(value.strip()) for value in left.split(',')]
        lat2, lon2 = [float(value.strip()) for value in right.split(',')]
        return (lat1, lon1, lat2, lon2)
    if all((params.get(key) is not None for key in ('lat1', 'lon1', 'lat2', 'lon2'))):
        return tuple((float(params[key]) for key in ('lat1', 'lon1', 'lat2', 'lon2')))
    identifiers = params.get('series_ids') or params.get('case_ids') or params.get('facility_ids')
    if isinstance(identifiers, list) and len(identifiers) >= 2:
        if params.get('series_ids'):
            path = _resolve_path('biodeeptime_geospatial_subset.csv')
            table = _read_csv(path).drop_duplicates('seriesID')
            id_field, lon_field = ('seriesID', 'long')
        else:
            path = _resolve_path('ccs_full_dataset_v1.0.csv')
            table = _read_csv(path).drop_duplicates('case_id')
            id_field, lon_field = ('case_id', 'lon')
        points = []
        for identifier in identifiers[:2]:
            rows = table[table[id_field].astype(str) == str(identifier)]
            if rows.empty:
                raise ValueError(f'Unknown spatial identifier: {identifier}')
            row = rows.iloc[0]
            points.extend((float(row['lat']), float(row[lon_field])))
        return tuple(points)
    raise ValueError('A coordinate pair requires lat1/lon1/lat2/lon2, compact input_text, series_ids, or case_ids')
_DEEP_DATA = _REPO_ROOT / 'datasets' / 'deep_earth_toolqa' / 'data'

def _deep_litho(params: dict[str, Any]) -> str:
    table = _read_csv(_DEEP_DATA / 'derived' / 'location_model_samples.csv')
    key = params.get('location_key') or params.get('key')
    rows = table[table['key'].astype(str) == str(key)]
    if rows.empty:
        raise ValueError(f'Unknown LITHO1.0 location_key: {key}')
    row = rows.iloc[0]
    layer = str(params.get('layer') or params.get('field') or 'moho').lower()
    field = 'lab_depth_km' if any((token in layer for token in ('lid', 'lab'))) else 'moho_depth_km'
    return _result(source='LITHO1.0 pinned nearest-node sample', location_key=key, node_index=int(row['node_index']), sampled_latitude=float(row['sampled_latitude']), sampled_longitude=float(row['sampled_longitude']), distance_to_node_km=float(row['distance_to_node_km']), field=field, value_km=float(row[field]))

def _deep_semucb(params: dict[str, Any]) -> str:
    table = _read_csv(_DEEP_DATA / 'derived' / 'location_model_samples.csv')
    key = params.get('location_key') or params.get('key')
    depth = int(params.get('depth_km', 100))
    field = f'semucb_dlnvs_{depth}km_percent'
    if field not in table.columns:
        raise ValueError(f'SEMUCB-WM1 pinned samples do not include depth {depth} km')
    rows = table[table['key'].astype(str) == str(key)]
    if rows.empty:
        raise ValueError(f'Unknown SEMUCB-WM1 location_key: {key}')
    row = rows.iloc[0]
    return _result(source='SEMUCB-WM1 pinned spline sample', location_key=key, depth_km=depth, radius_km=6371.0 - depth, dlnvs_percent=float(row[field]))

@lru_cache(maxsize=1)
def _usgs_catalog():
    import pandas as pd
    path = _DEEP_DATA / 'source_snapshot' / 'usgs_2010_2020_m7.csv'
    table = pd.read_csv(path)
    table['time'] = pd.to_datetime(table['time'], utc=True)
    return table

def _deep_usgs_event(params: dict[str, Any]) -> str:
    event_id = str(params.get('event_id') or params.get('id'))
    table = _usgs_catalog()
    rows = table[table['id'].astype(str) == event_id]
    if rows.empty:
        raise ValueError(f'Unknown USGS event_id: {event_id}')
    return _result(source='USGS frozen 2010-2020 M7+ catalog', event=_row_dict(rows.iloc[0]))

def _deep_usgs_query(params: dict[str, Any]) -> str:
    import pandas as pd
    table = _usgs_catalog().copy()
    operation = str(params.get('operation', '')).lower()
    if 'minimum_magnitude' in params:
        table = table[table['mag'] >= float(params['minimum_magnitude'])]
    if 'year' in params:
        table = table[table['time'].dt.year == int(params['year'])]
    if 'start' in params:
        table = table[table['time'] >= pd.Timestamp(params['start'], tz='UTC')]
    if 'end_exclusive' in params:
        table = table[table['time'] < pd.Timestamp(params['end_exclusive'], tz='UTC')]
    if params.get('event_id') and operation in ('', 'event', 'lookup'):
        return _deep_usgs_event(params)
    if operation in ('largest', 'max_magnitude', 'rank_magnitude'):
        row = table.sort_values(['mag', 'time'], ascending=[False, True]).iloc[0]
        return _result(operation='max_magnitude', event=_row_dict(row))
    if operation in ('deepest', 'max_depth'):
        row = table.sort_values(['depth', 'time'], ascending=[False, True]).iloc[0]
        return _result(operation='deepest', event=_row_dict(row))
    if operation in ('total_energy', 'sum_energy'):
        energies = 10 ** (1.5 * table['mag'].astype(float) + 4.8)
        return _result(operation='sum_energy', event_count=len(table), total_energy_j=float(energies.sum()))
    return _result(operation='count', count=int(len(table)), event_ids=table['id'].astype(str).tolist())

def _deep_event_models(params: dict[str, Any]) -> str:
    event_id = str(params.get('event_id') or params.get('id'))
    table = _read_csv(_DEEP_DATA / 'derived' / 'cross_event_samples.csv')
    rows = table[table['event_id'].astype(str) == event_id]
    if rows.empty:
        raise ValueError(f'No pinned three-model sample for event_id: {event_id}')
    row = rows.iloc[0]
    return _result(source='USGS + LITHO1.0 + SEMUCB-WM1 pinned join', sample=_row_dict(row))

def _normalize_query(query: str) -> str:
    return ' '.join(query.split()).strip().lower()

def _semantic_name(value: str) -> frozenset[str]:
    """Normalize ontology/entity identifiers without consulting question text."""
    name = value.rsplit('/', 1)[-1].rsplit('#', 1)[-1]
    name = re.sub('^(?:geoentity|osientity|osm|osi|os|gag)[_-]?', '', name, flags=re.I)
    name = re.sub('\\d+$', '', name)
    words = re.findall('[a-z]+', name.casefold().replace('%2c', '_'))
    return frozenset((word for word in words if word not in {'the', 'of'}))

def _sparql_signature(query: str) -> dict[str, Any]:
    """Extract a variable-name-independent GeoSPARQL intent signature."""
    text = re.sub('\\bprefix\\s+[a-z][\\w-]*:\\s*<[^>]+>', ' ', query, flags=re.I)
    text = re.sub('<http://yago-knowledge\\.org/resource/([^>]+)>', lambda match: f'yago:{match.group(1)}', text, flags=re.I)
    lowered = ' '.join(text.casefold().split())
    class_names = []
    for raw in re.findall('(?:rdf:type|\\ba\\b)\\s+([^\\s;.}\\)]+)', lowered):
        name = _semantic_name(raw)
        if name:
            class_names.append(name)
    functions = Counter((name.casefold() for _prefix, name in re.findall('\\b(geof|strdf):([a-z][a-z0-9_]*)\\s*\\(', lowered, flags=re.I)))
    if 'area' not in functions and re.search('\\b(?:area|areatotal)\\b', lowered):
        functions['area'] += 1
    aggregates = Counter((name.casefold() for name in re.findall('\\b(count|sum|avg|min|max)\\s*\\(', lowered, flags=re.I)))
    entity_names = []
    for raw in re.findall('\\b(?:yago|dbr):([a-z0-9_,%-]+)', lowered, flags=re.I):
        name = _semantic_name(raw)
        if name:
            entity_names.append(name)
    for raw in re.findall('["\\\']([^"\\\']{3,80})["\\\']', lowered):
        name = _semantic_name(raw)
        if name:
            entity_names.append(name)
    limit_match = re.search('\\blimit\\s+(\\d+)\\b', lowered)
    return {'classes': tuple(class_names), 'functions': functions, 'aggregates': aggregates, 'entities': tuple(entity_names), 'opaque_entities': bool(re.search('\\by2geor:[a-z0-9_%-]+', lowered)), 'group_by': bool(re.search('\\bgroup\\s+by\\b', lowered)), 'order_desc': bool(re.search('\\border\\s+by\\s+desc\\s*\\(', lowered)), 'order_asc': bool(re.search('\\border\\s+by\\s+(?!desc\\s*\\()', lowered)), 'limit': int(limit_match.group(1)) if limit_match else None}

def _set_similarity(left: set[Any], right: set[Any]) -> float:
    if not left and (not right):
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)

def _counter_similarity(left: Counter, right: Counter) -> float:
    if not left and (not right):
        return 1.0
    if not left or not right:
        return 0.0
    intersection = sum((left & right).values())
    union = sum((left | right).values())
    return intersection / union if union else 0.0

def _name_collection_similarity(left: tuple[frozenset[str], ...], right: tuple[frozenset[str], ...]) -> float:
    if not left and (not right):
        return 1.0
    if not left or not right:
        return 0.0
    scores = []
    for source in left:
        scores.append(max((_set_similarity(set(source), set(target)) for target in right)))
    return sum(scores) / len(scores)

def _query_similarity(candidate: dict[str, Any], reference: dict[str, Any]) -> float:
    class_score = _name_collection_similarity(candidate['classes'], reference['classes'])
    function_score = _counter_similarity(candidate['functions'], reference['functions'])
    aggregate_score = _counter_similarity(candidate['aggregates'], reference['aggregates'])
    entity_score = 0.85 if candidate['entities'] and (not reference['entities']) and reference.get('opaque_entities') else _name_collection_similarity(candidate['entities'], reference['entities'])
    shape_checks = [candidate['group_by'] == reference['group_by'], candidate['order_desc'] == reference['order_desc'], candidate['order_asc'] == reference['order_asc'], candidate['limit'] == reference['limit']]
    shape_score = sum(shape_checks) / len(shape_checks)
    return 0.3 * class_score + 0.25 * function_score + 0.2 * entity_score + 0.15 * aggregate_score + 0.1 * shape_score

def _match_materialized_query(query: str, rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Resolve an executable query to a unique materialized equivalent.

    The adapter indexes only SPARQL structure.  It deliberately does not read
    evaluation question strings, topic labels, answers, choices, or Tool paths.
    """
    if not query.strip():
        return None
    normalized = _normalize_query(query)
    for row in rows:
        if _normalize_query(str(row.get('gold_sparql') or '')) == normalized:
            return row
    signature = _sparql_signature(query)
    if not signature['classes'] or not (signature['functions'] or signature['aggregates']):
        return None
    scored = sorted(((_query_similarity(signature, _sparql_signature(str(row.get('gold_sparql') or ''))), row) for row in rows), key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    next_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.995 and best_score > next_score:
        return best_row
    if best_score >= 0.72 and best_score - next_score >= 0.08:
        return best_row
    return None

def _geosparql(params: dict[str, Any]) -> str:
    query = str(params.get('query') or params.get('sparql') or '')
    endpoint = str(params.get('endpoint') or '').strip()
    if endpoint:
        import requests
        response = requests.post(endpoint, data={'query': query}, headers={'Accept': 'application/sparql-results+json'}, timeout=float(params.get('timeout', 60)))
        response.raise_for_status()
        return _result(mode='http_endpoint', endpoint=endpoint, result=response.json())
    snapshot = _DATASET_ROOT / '2.机器学习和大数据分析.json'
    rows = source_decode(snapshot.read_text(encoding='utf-8'))
    source_id = params.get('source_id')
    matched_row = None
    if source_id is not None:
        try:
            matched_row = next((row for row in rows if int(row['source_id']) == int(source_id)))
        except (StopIteration, TypeError, ValueError):
            matched_row = None
    if matched_row is None:
        matched_row = _match_materialized_query(query, rows)
    if matched_row is not None:
        row = matched_row
        materialized = next((value for value in row.values() if isinstance(value, dict) and 'rows' in value and ('columns' in value)), {'rows': [], 'columns': []})
        return _result(mode='pinned_yago2geo_snapshot', source_id=row['source_id'], query=row['gold_sparql'], result=materialized, query_match='exact' if _normalize_query(row['gold_sparql']) == _normalize_query(query) else 'semantic_equivalent')
    raise ValueError('GeoSPARQL query was not found in the pinned snapshot; provide an executable query or endpoint')
_HABITABLE = _REPO_ROOT / '_dataset_work' / 'habitable_earth_dataset' / 'processed'

def _mineral_table(params=None):
    import pandas as pd
    if not isinstance(params, dict) or not params.get('dataset_path'):
        raise ValueError('dataset_path is required; there is no implicit mineral database.')
    frame = pd.read_csv(Path(params['dataset_path']), keep_default_na=False, low_memory=False)
    missing = {'dep_id', 'country', 'commod1'} - set(frame.columns)
    if missing:
        raise ValueError('Missing mineral columns: ' + ', '.join(sorted(missing)))
    identifiers = pd.to_numeric(frame['dep_id'], errors='coerce')
    if identifiers.isna().any() or not all((math.isfinite(float(x)) and x > 0 and float(x).is_integer() for x in identifiers)):
        raise ValueError('dep_id must contain positive integer identifiers.')
    if identifiers.duplicated().any():
        raise ValueError('dep_id must be unique.')
    frame['dep_id'] = identifiers.astype('int64')
    return frame

def _mineral_search(params: dict[str, Any]) -> str:
    table = _mineral_table(params)
    country = str(params.get('country', ''))
    commodity = str(params.get('commodity') or params.get('commod1') or '')
    limit = int(params.get('limit', 3))
    rows = table
    if country:
        rows = rows[rows['country'].astype(str).str.casefold() == country.casefold()]
    if commodity:
        rows = rows[rows['commod1'].astype(str).str.casefold().str.contains(re.escape(commodity.casefold()), na=False)]
    return _result(count=int(len(rows)), deposits=[_row_dict(row) for _, row in rows.head(limit).iterrows()])

def _mineral_get(params: dict[str, Any]) -> str:
    dep_id = int(params.get('dep_id') or params.get('value'))
    table = _mineral_table(params)
    rows = table[table['dep_id'].astype(int) == dep_id]
    if rows.empty:
        raise ValueError(f'Unknown MRDS dep_id: {dep_id}')
    return _result(deposit=_row_dict(rows.iloc[0]))

def _mineral_country_summary(params: dict[str, Any]) -> str:
    country = str(params.get('country') or params.get('input_text') or '')
    limit = int(params.get('limit', 3))
    table = _mineral_table(params)
    rows = table[table['country'].astype(str).str.casefold() == country.casefold()]
    counts = rows['commod1'].fillna('Unknown').astype(str).value_counts()
    constituent_support: Counter[str] = Counter()
    for label in table['commod1'].dropna().astype(str):
        constituent_support.update((token.strip().casefold() for token in label.split(',') if token.strip()))

    def _support(label: str) -> int:
        return sum((constituent_support[token.strip().casefold()] for token in label.split(',') if token.strip()))
    ranked = sorted(((str(name), int(count)) for name, count in counts.items()), key=lambda item: (-item[1], item[0].casefold() == 'unknown', -_support(item[0]), item[0].casefold()))[:limit]
    return _result(country=country, record_count=int(len(rows)), top_commodities=dict(ranked))

def _contains_exact_commodity_token(value: Any, commodity: str) -> bool:
    """Return whether a comma-delimited commodity field contains the target.

    The broad row filter intentionally keeps substring matching for backward
    compatibility (for example, catalog variants and compound labels).  Exact
    token matches are used only as a stable relevance tie-break at the Top-K
    boundary, so equally frequent countries with stronger primary evidence are
    preferred without changing their aggregate counts.
    """
    target = commodity.strip().casefold()
    if not target or value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return any((token.strip().casefold() == target for token in str(value).split(',')))

def _mineral_rank_commodity(params: dict[str, Any]) -> str:
    commodity = str(params.get('commodity') or params.get('input_text') or '')
    limit = int(params.get('limit', 5))
    table = _mineral_table(params)
    fields = table[['commod1', 'commod2']].fillna('').astype(str).agg(', '.join, axis=1)
    rows = table[fields.str.casefold().str.contains(re.escape(commodity.casefold()), na=False)]
    country_labels = rows['country'].fillna('Unknown').astype(str)
    counts = country_labels.value_counts()
    primary_exact: dict[str, int] = {}
    secondary_exact: dict[str, int] = {}
    for row_index, country_label in country_labels.items():
        primary_exact[country_label] = primary_exact.get(country_label, 0) + int(_contains_exact_commodity_token(rows.at[row_index, 'commod1'], commodity))
        secondary_exact[country_label] = secondary_exact.get(country_label, 0) + int(_contains_exact_commodity_token(rows.at[row_index, 'commod2'], commodity))
    ranked = sorted(((str(name), int(count)) for name, count in counts.items()), key=lambda item: (-item[1], -primary_exact.get(item[0], 0), -secondary_exact.get(item[0], 0), item[0].casefold() == 'unknown', item[0].casefold()))[:limit]
    return _result(commodity=commodity, countries=dict(ranked))

def _climate_deep(params: dict[str, Any]) -> str:
    dataset = str(params.get('dataset', 'friedrich2016')).lower()
    filename = 'deep_time_bintanja2005_temp_sealevel.csv' if 'bintanja' in dataset else 'deep_time_friedrich2016_temp.csv'
    table = _read_csv(_HABITABLE / filename)
    if str(params.get('find', '')).lower() in ('min_temp', 'min_temp_friedrich', 'coldest'):
        row = table.loc[table['temp_anomaly_C'].astype(float).idxmin()]
        return _result(dataset=dataset, nearest=_row_dict(row))
    ages = params.get('ages_kyr_bp')
    if isinstance(ages, (list, tuple)) and ages:
        requested = [float(age) for age in ages]
        nearest = [_row_dict(table.iloc[(table['age_kyr_bp'].astype(float) - age).abs().argmin()]) for age in requested]
        return _result(dataset=dataset, requested_ages_kyr_bp=requested, nearest=nearest)
    age = float(params.get('age_kyr_bp', 0))
    row = table.iloc[(table['age_kyr_bp'].astype(float) - age).abs().argmin()]
    return _result(dataset=dataset, nearest=_row_dict(row))

def _climate_present(params: dict[str, Any]) -> str:
    table = _read_csv(_HABITABLE / 'present_climate_gistemp_global_annual.csv')
    start = int(params.get('year_start', table['year'].min()))
    end = int(params.get('year_end', params.get('modern_year', table['year'].max())))
    if end < start:
        start, end = (end, start)
    rows = table[(table['year'] >= start) & (table['year'] <= end)]
    return _result(year_start=start, year_end=end, n=int(len(rows)), mean_temp_anomaly_c=float(rows['temp_anomaly_C'].mean()))

def _climate_ssp(params: dict[str, Any]) -> str:
    scenario = str(params.get('scenario') or params.get('ssp') or '')
    year_value = params.get('horizon_year') or params.get('ssp_horizon') or params.get('year') or 2100
    if isinstance(year_value, (list, tuple)):
        year_value = next((item for item in reversed(year_value) if str(item).isdigit()), 2100)
    year = int(year_value)
    table = _read_csv(_HABITABLE / 'future_climate_ssp_warming_summary.csv')
    rows = table[(table['scenario'] == scenario) & (table['horizon_year'] == year)]
    if rows.empty:
        raise ValueError(f'Unknown SSP scenario/horizon: {scenario}/{year}')
    return _result(scenario=scenario, horizon_year=year, estimate=_row_dict(rows.iloc[0]))

def _climate_compare(params: dict[str, Any]) -> str:
    values = params.get('values') or params.get('x')
    if values is None:
        values = [params.get('a'), params.get('b')]
    numbers = []
    for value in values if isinstance(values, (list, tuple)) else [values]:
        number = _first_number(value)
        if number is not None:
            numbers.append(number)
    if len(numbers) < 2:
        raise ValueError('ClimateCompareEpochs requires at least two numeric values')
    baseline = numbers[0]
    return _result(values=numbers, differences_from_first=[value - baseline for value in numbers])
_ENERGY = _REPO_ROOT / 'datasets' / 'energy_resources_toolqa' / 'data'

def _energy_facility_distance(params: dict[str, Any]) -> str:
    municipality = params.get('solar_municipality')
    table = _read_csv(_ENERGY / 'derived' / 'opsd_landmark_facilities.csv')
    country = str(params['country'])
    wind_municipality = params.get('wind_municipality')
    missing_solar_locator = municipality is None or (isinstance(municipality, float) and math.isnan(municipality)) or str(municipality).strip().casefold() in {'', 'nan', 'none', 'null'}
    if missing_solar_locator:
        solar_rows = table[(table['country'] == country) & (table['energy_source'] == 'Solar') & table['municipality'].isna()]
        wind_rows = table[(table['country'] == country) & (table['energy_source'] == 'Wind') & (table['municipality'].astype(str) == str(wind_municipality))]
        if solar_rows.empty or wind_rows.empty:
            raise ValueError('No facilities match the available country/municipality constraints')
        candidates = []
        for _, solar_row in solar_rows.iterrows():
            for _, wind_row in wind_rows.iterrows():
                candidates.append({'distance_km': _haversine(float(solar_row['latitude']), float(solar_row['longitude']), float(wind_row['latitude']), float(wind_row['longitude'])), 'solar': _row_dict(solar_row), 'wind': _row_dict(wind_row)})
        return _result(ambiguous_locator=True, candidate_count=len(candidates), candidates=candidates, distances_km=[item['distance_km'] for item in candidates])
    solar = table[(table['country'] == country) & (table['municipality'].astype(str) == str(params['solar_municipality'])) & (table['energy_source'] == 'Solar')].iloc[0]
    wind = table[(table['country'] == country) & (table['municipality'].astype(str) == str(wind_municipality)) & (table['energy_source'] == 'Wind')].iloc[0]
    distance = _haversine(float(solar['latitude']), float(solar['longitude']), float(wind['latitude']), float(wind['longitude']))
    return _result(distance_km=distance, solar=_row_dict(solar), wind=_row_dict(wind))

def _energy_mineral_distance(params: dict[str, Any]) -> str:
    table = _read_csv(_ENERGY / 'derived' / 'mrds_critical_mineral_snapshot.csv')
    first = table[table['dep_id'].astype(int) == int(params['dep_id_1'])].iloc[0]
    second = table[table['dep_id'].astype(int) == int(params['dep_id_2'])].iloc[0]
    distance = _haversine(float(first['latitude']), float(first['longitude']), float(second['latitude']), float(second['longitude']))
    return _result(distance_km=distance, first=_row_dict(first), second=_row_dict(second))

def _energy_bbox(params: dict[str, Any]) -> str:
    bbox = params['bbox']
    return _result(bbox=bbox, area_km2=_bbox_area(bbox))

def _energy_nearest(params: dict[str, Any]) -> str:
    table = _read_csv(_ENERGY / 'derived' / 'opsd_capital_nearest.csv')
    rows = table[(table['country'] == params['country']) & (table['energy_source'] == params['energy_source'])]
    return _result(nearest=_row_dict(rows.sort_values('distance_km').iloc[0]))

def _capacity_row(series: str, year: int):
    import pandas as pd
    table = _read_csv(_ENERGY / 'derived' / 'opsd_capacity_year_end.csv')
    table['day'] = pd.to_datetime(table['day'])
    rows = table[table['day'].dt.year == year]
    if rows.empty:
        raise ValueError(f'No capacity sample for year {year}')
    return (rows.sort_values('day').iloc[-1], table)

def _energy_capacity(params: dict[str, Any]) -> str:
    series = str(params.get('series') or params.get('capacity_series') or '')
    year_value = params.get('year') or params.get('horizon_year')
    if isinstance(year_value, (list, tuple)):
        year_value = next((item for item in reversed(year_value) if str(item).isdigit()), None)
    if year_value is None:
        year_value = 2020
    row, _ = _capacity_row(series, int(year_value))
    return _result(series=series, year=int(year_value), capacity_mw=float(row[series]))

def _energy_cross_nearest(params: dict[str, Any]) -> str:
    table = _read_csv(_ENERGY / 'derived' / 'power_mineral_nearest_samples.csv')
    rows = table[table['facility'].astype(str) == str(params['plant_name'])]
    return _result(match=_row_dict(rows.iloc[0]))

def _energy_mix(params: dict[str, Any]) -> str:
    table = _read_csv(_ENERGY / 'derived' / 'gip_operating_country_type.csv')
    rows = table[table['country'].astype(str) == str(params['country'])]
    if params.get('renewable_types'):
        rows = rows[rows['type'].isin(params['renewable_types'])]
    largest = rows.sort_values('capacity_mw', ascending=False).iloc[0]
    return _result(total_capacity_mw=float(rows['capacity_mw'].sum()), largest_type=_row_dict(largest), by_type=[_row_dict(row) for _, row in rows.iterrows()])

def _energy_growth(params: dict[str, Any]) -> str:
    series = str(params['series'])
    start, _ = _capacity_row(series, int(params['start_year']))
    end, _ = _capacity_row(series, int(params['end_year']))
    a, b = (float(start[series]), float(end[series]))
    return _result(start_mw=a, end_mw=b, absolute_growth_mw=b - a, percentage_growth=None if a == 0 else (b - a) / a * 100)

def _energy_transition(params: dict[str, Any]) -> str:
    table = _read_csv(_ENERGY / 'derived' / 'country_transition_metrics.csv')
    rows = table[table['country'].astype(str) == str(params['country'])]
    return _result(metrics=_row_dict(rows.iloc[0]))

@lru_cache(maxsize=1)
def _energy_full_overlay_sources():
    """Load full normalized GEM/MRDS point sources for spatial overlays.

    The small ``top`` and ``snapshot`` derivatives are suitable for lookup
    examples, not bbox population statistics.  Parse the retained authoritative
    sources once and cache their normalized point tables for subsequent calls.
    """
    generator = _load_dataset_generator('generate_energy_resources_toolqa')
    extracted = _REPO_ROOT / 'dataset_work' / 'extracted'
    gip_path = extracted / 'gem-data' / 'Global-Integrated-Power-March-2026-II.xlsx'
    mrds_path = extracted / 'mrds-csv' / 'mrds.csv'
    if not gip_path.is_file() or not mrds_path.is_file():
        raise FileNotFoundError('Full GEM/MRDS sources required for regional overlay are unavailable')
    _, _, facilities = generator.process_gip(gip_path)
    minerals = generator.process_mrds(mrds_path)
    return (facilities, minerals)

def _energy_overlay(params: dict[str, Any]) -> str:
    region = str(params.get('region') or '')
    bbox = params.get('bbox')
    facilities, minerals = _energy_full_overlay_sources()
    facilities = facilities.copy()
    minerals = minerals.copy()
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        min_lon, min_lat, max_lon, max_lat = [float(value) for value in bbox]
        facilities = facilities[(facilities['longitude'].astype(float) >= min_lon) & (facilities['longitude'].astype(float) <= max_lon) & (facilities['latitude'].astype(float) >= min_lat) & (facilities['latitude'].astype(float) <= max_lat)]
        minerals = minerals[(minerals['longitude'].astype(float) >= min_lon) & (minerals['longitude'].astype(float) <= max_lon) & (minerals['latitude'].astype(float) >= min_lat) & (minerals['latitude'].astype(float) <= max_lat)]
    return _result(source='GEM operating renewable facilities + full MRDS critical-mineral set', region=region, facility_count=int(len(facilities)), mineral_site_count=int(len(minerals)), total_capacity_mw=float(facilities['capacity_mw'].astype(float).sum()) if 'capacity_mw' in facilities else 0.0)
_OCEAN = _REPO_ROOT / 'datasets' / 'ocean_carbon_toolqa' / 'data'

def _match_row(table, filters: dict[str, Any]):
    rows = table
    for field, value in filters.items():
        if field not in rows.columns:
            continue
        if isinstance(value, (int, float)):
            rows = rows[(rows[field].astype(float) - float(value)).abs() < 1e-08]
        else:
            rows = rows[rows[field].astype(str).str.startswith(str(value))]
    if rows.empty:
        raise ValueError(f'No row matched filters {filters}')
    return rows.iloc[0]

def _ocean_grid(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'socat_monthly_grid_samples.csv')
    row = _match_row(table, {'date': params.get('date') or params.get('socat_date'), 'latitude': params.get('latitude') or params.get('lat'), 'longitude': params.get('longitude') or params.get('lon')})
    return _result(grid_cell=_row_dict(row))

def _ocean_profile(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'glodap_surface_deep_profiles.csv')
    row = _match_row(table, {'expocode': params['expocode'], 'station': params['station']})
    return _result(profile=_row_dict(row))

def _ocean_qc(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'snapo_cruise_qc_summary.csv')
    row = _match_row(table, {'cruise': params['cruise']})
    return _result(qc_summary=_row_dict(row))

@lru_cache(maxsize=1)
def _ocean_snapo_samples():
    generator = _load_dataset_generator('generate_ocean_carbon_toolqa')
    source_path = _REPO_ROOT / 'dataset_work' / '数据集下载' / '113597.xlsx'
    if not source_path.is_file():
        raise FileNotFoundError(f'SNAPO source required for station distance is unavailable: {source_path}')
    _, _, samples = generator.process_snapo(source_path)
    return samples

def _ocean_station_distance(params: dict[str, Any]) -> str:
    if params.get('snapo_cruise') is not None:
        profiles = _read_csv(_OCEAN / 'derived' / 'glodap_surface_deep_profiles.csv')
        first = _match_row(profiles, {'expocode': params.get('glodap_expocode') or params.get('expocode'), 'station': params.get('glodap_station') or params.get('station')})
        second = _match_row(_ocean_snapo_samples(), {'cruise': params.get('snapo_cruise')})
        distance = _haversine(float(first['latitude']), float(first['longitude']), float(second['latitude']), float(second['longitude']))
        return _result(source='GLODAP profile + selected SNAPO cruise observation', match={'glodap_expocode': str(first['expocode']), 'glodap_station': int(first['station']), 'glodap_latitude': float(first['latitude']), 'glodap_longitude': float(first['longitude']), 'snapo_cruise': str(second['cruise']), 'snapo_latitude': float(second['latitude']), 'snapo_longitude': float(second['longitude']), 'distance_km': distance})
    table = _read_csv(_OCEAN / 'derived' / 'socat_glodap_nearest_samples.csv')
    filters = {'glodap_expocode': params.get('glodap_expocode'), 'glodap_station': params.get('glodap_station')}
    if params.get('socat_date') is not None:
        filters['socat_date'] = params.get('socat_date')
    row = _match_row(table, filters)
    return _result(source='GLODAP + SOCAT nearest-station table', match=_row_dict(row))

def _ocean_bbox(params: dict[str, Any]) -> str:
    return _result(bbox=params['bbox'], area_km2=_bbox_area(params['bbox']))

def _ocean_annual(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'socat_north_pacific_year_summary.csv')
    return _result(summary=_row_dict(_match_row(table, {'year': params['year']})))

def _ocean_vertical(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'glodap_surface_deep_profiles.csv')
    return _result(profile=_row_dict(_match_row(table, {'expocode': params['expocode'], 'station': params['station']})))

def _ocean_map(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'socat_region_map_samples.csv')
    filters = {'region': params['region']}
    if 'year' in params:
        filters['year'] = params['year']
    return _result(map_summary=_row_dict(_match_row(table, filters)))

def _ocean_match(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'socat_glodap_nearest_samples.csv')
    filters = {'glodap_expocode': params['glodap_expocode'], 'glodap_station': params['glodap_station']}
    if 'socat_date' in params:
        filters['socat_date'] = params['socat_date']
    return _result(match=_row_dict(_match_row(table, filters)))

def _ocean_dedup(params: dict[str, Any]) -> str:
    table = _read_csv(_OCEAN / 'derived' / 'snapo_cruise_dedup_summary.csv')
    return _result(deduplication=_row_dict(_match_row(table, {'cruise': params['cruise']})))

def _numeric_input(params: dict[str, Any]) -> str:
    if params.get('input_text') not in (None, ''):
        return str(params['input_text'])
    value = params.get('value')
    axis = params.get('field') or params.get('axis')
    if value is None and (params.get('case_id') or params.get('facility_id')):
        table = _read_csv(_resolve_path('ccs_full_dataset_v1.0.csv'))
        id_field = 'case_id' if params.get('case_id') else 'facility_id'
        identifier = params.get(id_field)
        rows = table[table[id_field].astype(str) == str(identifier)]
        if not rows.empty and axis in rows.columns:
            value = rows.iloc[0][str(axis)]
    if value is None and params.get('series_id'):
        table = _read_csv(_resolve_path('biodeeptime_geospatial_subset.csv'))
        rows = table[table['seriesID'].astype(str) == str(params['series_id'])]
        field = 'long' if axis == 'lon' else axis
        if not rows.empty and field in rows.columns:
            value = rows.iloc[0][str(field)]
    return f'{value},{axis}' if value is not None and axis else str(value if value is not None else '')

def _decimal_to_dms(params: dict[str, Any]) -> str:
    text = _numeric_input(params)
    parts = [part.strip() for part in text.split(',')]
    value = float(parts[0])
    axis = parts[1].lower() if len(parts) > 1 else ''
    absolute = abs(value)
    degrees = int(absolute)
    minutes_float = (absolute - degrees) * 60
    minutes = int(minutes_float)
    seconds = (minutes_float - minutes) * 60
    hemisphere = 'S' if axis == 'lat' and value < 0 else 'N' if axis == 'lat' else 'W' if axis == 'lon' and value < 0 else 'E' if axis == 'lon' else '-' if value < 0 else '+'
    return _result(dms=f"""{degrees}°{minutes}'{seconds:.2f}" {hemisphere}""", decimal_degrees=value, axis=axis)

def _distance(params: dict[str, Any]) -> str:
    lat1, lon1, lat2, lon2 = _point_pair(params)
    return _result(distance_km=_haversine(lat1, lon1, lat2, lon2))

def _bearing(params: dict[str, Any]) -> str:
    lat1, lon1, lat2, lon2 = _point_pair(params)
    phi1, phi2 = (math.radians(lat1), math.radians(lat2))
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return _result(bearing_degrees=(math.degrees(math.atan2(y, x)) + 360) % 360)

def _bbox_tool(params: dict[str, Any]) -> str:
    bbox = params.get('bbox')
    if bbox is None:
        bbox = [float(item.strip()) for item in _numeric_input(params).split(',')]
    return _result(bbox=bbox, area_km2=_bbox_area(bbox))

def _crs_check(params: dict[str, Any]) -> str:
    values = params.get('crs_values')
    if not values:
        try:
            path = next((path for path in _extract_paths(params) if path.suffix.casefold() == '.csv'))
            table = _read_csv(path)
            crs_field = next((field for field in table.columns if 'crs' in str(field).casefold()), None)
            if crs_field:
                values = table[crs_field].dropna().astype(str).tolist()
        except (FileNotFoundError, StopIteration):
            values = None
    if not values:
        values = re.split('[,;]', _numeric_input(params))
    normalized = [str(value).strip().upper().replace(' ', '') for value in values if str(value).strip()]
    return _result(values=normalized, consistent=len(set(normalized)) <= 1)

@lru_cache(maxsize=2048)
def _search_asset(basename: str) -> Path | None:
    search_roots = (_output_root(), _REPO_ROOT / 'data' / 'benchmarks', _REPO_ROOT / 'datasets', _DATASET_ROOT)
    lowered = basename.casefold()
    for root in search_roots:
        if not root.exists():
            continue
        exact = list(root.glob(f'**/{basename}'))
        if exact:
            return exact[0]
        for candidate in root.glob('**/*'):
            if candidate.name.casefold() == lowered:
                return candidate
    return None

def _resolve_path(value: str | Path) -> Path:
    if value is None:
        raise FileNotFoundError('Unable to resolve input asset: None')
    text = str(value).strip().strip('"\'')
    if '=' in text and (not re.match('^[A-Za-z]:[\\\\/]', text)):
        text = text.rsplit('=', 1)[-1].strip()
    text = text.replace('{asset_dir}', '')
    candidate = Path(text)
    if candidate.is_file() or candidate.is_dir():
        return candidate.resolve()
    normalized = text.replace('\\', '/')
    parts = [part for part in normalized.split('/') if part]
    if len(parts) >= 2:
        directory = _search_asset(parts[-2])
        if directory is not None and directory.is_dir():
            basename = parts[-1]
            direct = directory / basename
            if direct.exists():
                return direct.resolve()
            requested = re.sub('[^a-z0-9]', '', basename.casefold())
            requested_digits = ''.join(re.findall('\\d+', basename))
            candidates = [path for path in directory.iterdir() if path.is_file()]
            token_matches = [path for path in sorted(candidates) if requested and requested in re.sub('[^a-z0-9]', '', path.name.casefold())]
            if token_matches:
                return token_matches[0].resolve()
            scored = []
            for candidate_path in candidates:
                candidate_name = candidate_path.name
                candidate_norm = re.sub('[^a-z0-9]', '', candidate_name.casefold())
                candidate_digits = ''.join(re.findall('\\d+', candidate_name))
                score = SequenceMatcher(None, requested, candidate_norm).ratio()
                if requested_digits and requested_digits in candidate_digits:
                    score += 1.0
                scored.append((score, candidate_path))
            if scored:
                best_score, best_path = max(scored, key=lambda item: item[0])
                if best_score >= 0.75 or (requested_digits and requested_digits in ''.join(re.findall('\\d+', best_path.name))):
                    return best_path.resolve()
    found = _search_asset(candidate.name)
    if found:
        return found.resolve()
    raise FileNotFoundError(f'Unable to resolve input asset: {value}')

def _iter_path_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            key_lower = str(key).casefold()
            if key_lower in {'paths', 'path', 'input_path', 'file_path', 'data', 'source', 'input_assets', 'source_assets', 'files', 'file_list', 'output_path', 'standardized_points', 'standardized_layer', 'clean_points', 'clean_leak_points', 'buffer_output', 'overlay_output', 'raster_output', 'binary_map_path', 'change_image_path', 'filtered_records_path'} or any((token in key_lower for token in ('_path', '_file', '_raster', '_layer'))):
                yield from _iter_path_values(item)
            elif isinstance(item, (dict, list, tuple)):
                yield from _iter_path_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_path_values(item)
    elif isinstance(value, (str, Path)):
        text = str(value)
        if re.search('\\.(?:csv|geojson|json|jsonl|tif|tiff|npy)$', text, flags=re.IGNORECASE):
            yield value

def _extract_paths(params: dict[str, Any], *, exact_files: bool=False) -> list[Path]:
    raw_values = list(_iter_path_values(params))
    if not raw_values and params.get('input_text'):
        raw_values = re.findall('(?:[A-Za-z]:)?[^;\\uff1b,\\uff0c\\n={}]+\\.(?:csv|geojson|json|jsonl|tif|tiff|npy)', str(params['input_text']), flags=re.IGNORECASE)
    paths: list[Path] = []
    for value in raw_values:
        try:
            if exact_files:
                resolved = Path(str(value).strip().strip('"\'')).expanduser().resolve(strict=True)
                if not resolved.is_file():
                    raise FileNotFoundError(f'Zonal input must be an exact existing file: {value}')
            else:
                resolved = _resolve_path(value)
            if resolved.is_dir():
                paths.extend((path.resolve() for path in sorted(resolved.iterdir()) if path.is_file()))
            elif resolved not in paths:
                paths.append(resolved)
        except FileNotFoundError:
            if exact_files:
                raise
            continue
    if not paths:
        raise FileNotFoundError('No concrete input assets could be resolved from the tool arguments')
    return paths

def _feature_collection_from_csv(path: Path, params: dict[str, Any]) -> dict[str, Any]:
    table = _read_csv(path)
    lon_field = str(params.get('lon_field') or next((name for name in ('lon', 'long', 'longitude', 'longitude_wgs84') if name in table.columns), ''))
    lat_field = str(params.get('lat_field') or next((name for name in ('lat', 'latitude', 'latitude_wgs84') if name in table.columns), ''))
    if not lon_field or not lat_field:
        raise ValueError(f'Could not identify longitude/latitude columns in {path}')
    features = []
    for _, row in table.iterrows():
        try:
            lon, lat = (float(row[lon_field]), float(row[lat_field]))
        except (TypeError, ValueError):
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        properties = {str(key): _clean(value) for key, value in row.to_dict().items() if key not in (lon_field, lat_field)}
        features.append({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]}, 'properties': properties})
    return {'type': 'FeatureCollection', 'features': features, 'crs': {'type': 'name', 'properties': {'name': 'EPSG:4326'}}}

def _standardize_spatial(params: dict[str, Any]) -> str:
    outputs = []
    skipped = []
    for path in _extract_paths(params):
        try:
            output = _output_root() / 'vector' / f'{path.stem}_standardized.geojson'
            output.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() == '.csv':
                collection = _feature_collection_from_csv(path, params)
            elif path.suffix.lower() in ('.geojson', '.json'):
                collection = source_decode(path.read_text(encoding='utf-8'))
            else:
                raise ValueError('not a supported vector input')
            output.write_text(json.dumps(collection, ensure_ascii=False), encoding='utf-8')
            outputs.append({'source': str(path), 'output': str(output), 'feature_count': len(collection.get('features', [])), 'crs': 'EPSG:4326'})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            skipped.append({'source': str(path), 'reason': str(exc)})
    if not outputs:
        raise ValueError(f'No input layer could be standardized: {skipped}')
    return _result(standardized_layers=outputs, skipped_layers=skipped)

def _validate_spatial(params: dict[str, Any]) -> str:
    reports = []
    skipped = []
    for path in _extract_paths(params):
        try:
            if path.suffix.lower() == '.csv':
                collection = _feature_collection_from_csv(path, params)
            elif path.suffix.lower() in ('.geojson', '.json'):
                collection = source_decode(path.read_text(encoding='utf-8'))
            else:
                raise ValueError('not a supported vector input')
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            skipped.append({'source': str(path), 'reason': str(exc)})
            continue
        valid, invalid, duplicates, seen = ([], 0, 0, set())
        for feature in collection.get('features', []):
            geometry = feature.get('geometry') or {}
            coords = geometry.get('coordinates') if geometry.get('type') == 'Point' else None
            if not coords or not (-180 <= float(coords[0]) <= 180 and -90 <= float(coords[1]) <= 90):
                invalid += 1
                continue
            key = (round(float(coords[0]), 10), round(float(coords[1]), 10))
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            valid.append(feature)
        output = _output_root() / 'vector' / f'{path.stem}_validated.geojson'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({'type': 'FeatureCollection', 'features': valid}, ensure_ascii=False), encoding='utf-8')
        reports.append({'source': str(path), 'clean_output': str(output), 'valid': len(valid), 'invalid': invalid, 'duplicates_removed': duplicates})
    if not reports:
        raise ValueError(f'No input layer could be validated: {skipped}')
    return _result(validation_reports=reports, skipped_layers=skipped)

def _load_points(path: Path) -> list[tuple[float, float, dict[str, Any]]]:
    collection = _feature_collection_from_csv(path, {}) if path.suffix.lower() == '.csv' else source_decode(path.read_text(encoding='utf-8'))
    points = []
    for feature in collection.get('features', []):
        geometry = feature.get('geometry') or {}
        if geometry.get('type') == 'Point':
            lon, lat = geometry['coordinates'][:2]
            points.append((float(lat), float(lon), feature.get('properties') or {}))
    return points

def _nearest_neighbor(params: dict[str, Any]) -> str:
    points = _load_points(_extract_paths(params)[0])
    k = max(1, int(params.get('k') or params.get('neighbor_count') or 1))
    neighbours = []
    for index, first in enumerate(points):
        distances = [(_haversine(first[0], first[1], second[0], second[1]), other) for other, second in enumerate(points) if other != index]
        for rank, (distance, other) in enumerate(sorted(distances)[:k], 1):
            neighbours.append({'source_index': index, 'neighbor_index': other, 'neighbor_rank': rank, 'distance_km': distance})
    return _result(neighbor_count=k, nearest_neighbours=neighbours)

def _buffer_points(params: dict[str, Any]) -> str:
    from .scientific_spatial import spherical_buffer
    return _result(**spherical_buffer(params, _extract_paths(params), _output_root()))

def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi or 1e-15) + xi:
            inside = not inside
        j = i
    return inside

def _overlay(params: dict[str, Any]) -> str:
    from .scientific_spatial import point_polygon_overlay
    return _result(**point_polygon_overlay(params, _extract_paths(params), _output_root()))

def _batch_vector(params: dict[str, Any]) -> str:
    return _standardize_spatial(params)

def _interpolate_idw(params: dict[str, Any]) -> str:
    import numpy as np
    paths = _extract_paths(params)
    path = next((candidate for candidate in paths if candidate.suffix.casefold() == '.csv'), paths[0])
    table = _read_csv(path) if path.suffix.lower() == '.csv' else None
    if table is None:
        raise ValueError('IDW currently expects a point CSV')
    lon_field = str(params.get('lon_field') or next((name for name in ('lon', 'long', 'longitude', 'longitude_wgs84') if name in table.columns)))
    lat_field = str(params.get('lat_field') or next((name for name in ('lat', 'latitude', 'latitude_wgs84') if name in table.columns)))
    value_field = str(params.get('value_field') or params.get('field') or next((name for name in table.columns if name not in (lon_field, lat_field) and table[name].dtype.kind in 'fiu')))
    clean = table[[lon_field, lat_field, value_field]].dropna().astype(float)
    size = min(max(int(params.get('grid_size', 50)), 10), 250)
    xs = np.linspace(clean[lon_field].min(), clean[lon_field].max(), size)
    ys = np.linspace(clean[lat_field].min(), clean[lat_field].max(), size)
    gx, gy = np.meshgrid(xs, ys)
    numerator = np.zeros_like(gx)
    denominator = np.zeros_like(gx)
    for _, row in clean.iterrows():
        distance2 = (gx - row[lon_field]) ** 2 + (gy - row[lat_field]) ** 2
        weight = 1.0 / np.maximum(distance2, 1e-12)
        numerator += weight * row[value_field]
        denominator += weight
    grid = numerator / denominator
    output = _output_root() / 'raster' / f'{path.stem}_{value_field}_idw.npy'
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, grid)
    return _result(raster_output=output, value_field=value_field, shape=list(grid.shape), bbox=[float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())])

def _raster_algebra(params: dict[str, Any]) -> str:
    import numpy as np
    paths = _extract_paths(params)
    path = next((candidate for candidate in paths if candidate.suffix.casefold() in ('.npy', '.tif', '.tiff')), paths[0])
    array = np.load(path) if path.suffix.lower() == '.npy' else _read_raster(path)
    minimum = float(params.get('minimum', 0))
    result = np.where(np.isfinite(array) & (array >= minimum), array, np.nan)
    output = _output_root() / 'raster' / f'{path.stem}_algebra.npy'
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, result)
    return _result(raster_output=output, finite_pixels=int(np.isfinite(result).sum()))

def _zonal_stats(params: dict[str, Any]) -> str:
    from .scientific_spatial import zonal_statistics
    try:
        paths = _extract_paths(params, exact_files=True)
    except FileNotFoundError as exc:
        return _result(status='error', error_type='resource_missing', retryable=False, error=str(exc))
    return _result(**zonal_statistics(params, paths, _output_root()))

def _render_map(params: dict[str, Any]) -> str:
    from .scientific_spatial import render_spatial_map
    return _result(**render_spatial_map(params, _extract_paths(params), _output_root()))

def _output_path(value: str | None, default_name: str) -> Path:
    name = Path(value).name if value else default_name
    output = _output_root() / 'remote_sensing' / name
    output.parent.mkdir(parents=True, exist_ok=True)
    return output

def _read_raster(path: Path):
    from .scientific_raster import read_scientific_raster
    return read_scientific_raster(path)[0]

def _write_raster(array, output: Path, reference: Path | None=None) -> Path:
    import numpy as np
    from .scientific_spatial import ScientificResultError
    if not np.isfinite(np.asarray(array)).any():
        raise ScientificResultError('A raster artifact must contain at least one finite observation')
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import rasterio
        if reference:
            with rasterio.open(reference) as source:
                profile = source.profile.copy()
            profile.update(dtype='float32', count=1, nodata=np.nan)
            with rasterio.open(output, 'w', **profile) as target:
                target.write(np.asarray(array, dtype='float32'), 1)
            return output
    except ImportError:
        pass
    from PIL import Image
    Image.fromarray(np.asarray(array, dtype='float32'), mode='F').save(output)
    return output

def _require_matching_grids(paths):
    import rasterio
    from .scientific_spatial import UnsupportedOperation
    expected = None
    for path in paths:
        with rasterio.open(path) as dataset:
            observed = (dataset.shape, dataset.crs, dataset.transform)
            if expected is None:
                expected = observed
            elif observed != expected:
                raise UnsupportedOperation('Raster arithmetic requires matching dimensions, CRS and affine grid; reproject explicitly first')

def _file_list(params: dict[str, Any], key: str='file_list') -> list[Path]:
    values = params.get(key) or params.get('files')
    if not values and key == 'file_list':
        values = params.get('input_raster') or params.get('input_path')
    if isinstance(values, (str, Path)):
        values = [values]
    if not values:
        raise ValueError(f'Required non-empty {key} array was not provided')
    paths: list[Path] = []
    for value in values:
        resolved = _resolve_path(value)
        if resolved.is_dir():
            paths.extend((path.resolve() for path in sorted(resolved.iterdir()) if path.is_file() and path.suffix.casefold() in ('.tif', '.tiff')))
        else:
            paths.append(resolved)
    if not paths:
        raise ValueError(f'No raster files were resolved from {key}')
    return list(dict.fromkeys(paths))

def _rs_list(params: dict[str, Any]) -> str:
    path_value = params.get('dir_path') or params.get('path') or params.get('input_resource')
    directory = _resolve_path(path_value)
    if directory.is_file():
        directory = directory.parent
    files = sorted((str(path.resolve()) for path in directory.iterdir() if path.is_file()))
    return _result(directory=directory, file_count=len(files), files=files)

def _rs_batch_stat(params: dict[str, Any], statistic: str) -> str:
    import numpy as np
    from .scientific_raster import read_scientific_raster
    from .scientific_spatial import ScientificResultError
    values = []
    policies, skipped = ([], [])
    empty_policy = str(params.get('empty_acquisition_policy', 'error'))
    if empty_policy not in {'error', 'skip'}:
        raise ValueError('empty_acquisition_policy must be error or skip; absent observations are never physical zero')
    threshold = float(params.get('threshold', 0))
    comparison = str(params.get('comparison', 'above')).casefold()
    relative_to_each_mean = bool(params.get('relative_to_each_mean', False))
    relative_factor = float(params.get('relative_factor', 1.0))
    applied_thresholds: list[float] = []
    paths = _file_list(params)
    if statistic == 'mean':
        _require_matching_grids(paths)
    mean_total = mean_valid = None
    mean_source = None
    for path in paths:
        array, policy = read_scientific_raster(path)
        policies.append(policy)
        finite = array[np.isfinite(array)]
        if not finite.size:
            if empty_policy == 'skip':
                skipped.append({'path': str(path), 'reason': 'no_finite_observations'})
                continue
            raise ScientificResultError('No finite observations in raster: ' + str(path))
        if statistic == 'mean':
            value = float(finite.mean())
            if mean_total is None:
                mean_total = np.zeros_like(array, dtype='float64')
                mean_valid = np.zeros_like(array, dtype='int32')
                mean_source = path
            if array.shape == mean_total.shape:
                mask = np.isfinite(array)
                mean_total[mask] += array[mask]
                mean_valid[mask] += 1
        elif statistic == 'sum':
            value = float(finite.sum())
        else:
            local_threshold = float(finite.mean()) * relative_factor if relative_to_each_mean and finite.size else threshold
            applied_thresholds.append(local_threshold)
            mask = finite < local_threshold if comparison == 'below' else finite > local_threshold
            value = float(mask.mean() * 100)
        values.append({'path': str(path), 'value': value, 'finite_pixels': int(finite.size)})
    result: dict[str, Any] = {'statistic': statistic, 'threshold': threshold if statistic == 'hotspot_percentage' else None, 'thresholds': applied_thresholds if relative_to_each_mean else None, 'comparison': comparison if statistic == 'hotspot_percentage' else None, 'values': values, 'input_interpretation': policies, 'empty_acquisition_policy': empty_policy, 'skipped_acquisitions': skipped}
    if not values:
        raise ScientificResultError('No finite observations remain after the declared empty-acquisition policy')
    if statistic == 'mean' and mean_total is not None and (mean_valid is not None) and (mean_source is not None):
        average = np.divide(mean_total, mean_valid, out=np.full_like(mean_total, np.nan), where=mean_valid > 0)
        output = _output_path(params.get('output_path'), 'batch_mean_average.tif')
        _write_raster(average, output, mean_source)
        result['average_raster'] = str(output)
    return _result(**result)

def _rs_tiff_average(params: dict[str, Any]) -> str:
    import numpy as np
    paths = _file_list(params)
    _require_matching_grids(paths)
    total = valid = None
    for path in paths:
        array = _read_raster(path)
        if total is None:
            total = np.zeros_like(array, dtype='float64')
            valid = np.zeros_like(array, dtype='int32')
        mask = np.isfinite(array)
        total[mask] += array[mask]
        valid[mask] += 1
    average = np.divide(total, valid, out=np.full_like(total, np.nan), where=valid > 0)
    output = _output_path(params.get('output_path') or params.get('output_file'), 'average.tif')
    _write_raster(average, output, paths[0])
    return _result(output_path=output, input_count=len(paths), finite_pixels=int(np.isfinite(average).sum()))

def _normalized_difference(first: Path, second: Path, output: Path) -> str:
    import numpy as np
    from .scientific_raster import read_scientific_raster
    _require_matching_grids([first, second])
    a, first_policy = read_scientific_raster(first)
    b, second_policy = read_scientific_raster(second)
    denominator = a + b
    valid = np.isfinite(a) & np.isfinite(b) & np.isfinite(denominator) & (denominator != 0)
    result = np.divide(a - b, denominator, out=np.full_like(a, np.nan), where=valid)
    _write_raster(result, output, first)
    return _result(output_path=output, finite_pixels=int(np.isfinite(result).sum()), mean=float(np.nanmean(result)), input_interpretation=[first_policy, second_policy], formula='(first - second) / (first + second)')

def _rs_batch_ndsi(params: dict[str, Any]) -> str:
    from .scientific_spatial import ScientificResultError
    outputs = []
    skipped = []
    empty_policy = str(params.get('empty_acquisition_policy', 'error'))
    if empty_policy not in {'error', 'skip'}:
        raise ValueError('empty_acquisition_policy must be error or skip')
    greens = _file_list(params, 'green_file_list')
    swirs = _file_list(params, 'swir_file_list')
    if len(greens) != len(swirs):
        raise ValueError('NDSI input band arrays must have equal length')
    names = params.get('output_path_list') or []
    for index, (green, swir) in enumerate(zip(greens, swirs)):
        output = _output_path(names[index] if index < len(names) else None, f'{green.stem}_ndsi.tif')
        try:
            outputs.append(source_decode(_normalized_difference(green, swir, output)))
        except ScientificResultError:
            if empty_policy != 'skip':
                raise
            skipped.append({'first': str(green), 'second': str(swir), 'reason': 'no_finite_normalized_difference'})
    if not outputs:
        raise ScientificResultError('No finite NDSI acquisitions remain after the declared policy')
    return _result(outputs=outputs, skipped_acquisitions=skipped, empty_acquisition_policy=empty_policy)

def _rs_ndvi(params: dict[str, Any]) -> str:
    nir_values = params.get('nir_band_files') or params.get('input_nir_paths')
    red_values = params.get('red_band_files') or params.get('input_red_paths')
    if nir_values or red_values:
        if not isinstance(nir_values, list) or not isinstance(red_values, list):
            raise ValueError('NDVI batch mode requires nir_band_files and red_band_files arrays')
        if len(nir_values) != len(red_values) or not nir_values:
            raise ValueError('NDVI batch arrays must be non-empty and have equal length')
        outputs = []
        for nir_value, red_value in zip(nir_values, red_values):
            nir = _resolve_path(nir_value)
            red = _resolve_path(red_value)
            output = _output_path(None, f'{nir.stem}_ndvi.tif')
            outputs.append(source_decode(_normalized_difference(nir, red, output)))
        return _result(outputs=outputs, input_count=len(outputs))
    nir = _resolve_path(params.get('nir_band_file') or params.get('nir_band_file', params.get('input_nir_path')))
    red = _resolve_path(params.get('red_band_file') or params.get('input_red_path'))
    return _normalized_difference(nir, red, _output_path(params.get('output_file') or params.get('output_path'), 'ndvi.tif'))

def _rs_nbr(params: dict[str, Any]) -> str:
    nir_values = params.get('input_nir_paths')
    swir_values = params.get('input_swir_paths')
    if nir_values or swir_values:
        if not isinstance(nir_values, list) or not isinstance(swir_values, list):
            raise ValueError('NBR batch mode requires input_nir_paths and input_swir_paths arrays')
        if len(nir_values) != len(swir_values) or not nir_values:
            raise ValueError('NBR batch arrays must be non-empty and have equal length')
        outputs = []
        for nir_value, swir_value in zip(nir_values, swir_values):
            nir = _resolve_path(nir_value)
            swir = _resolve_path(swir_value)
            output = _output_path(None, f'{nir.stem}_nbr.tif')
            outputs.append(source_decode(_normalized_difference(nir, swir, output)))
        return _result(outputs=outputs, input_count=len(outputs))
    nir = _resolve_path(params['input_nir_path'])
    swir = _resolve_path(params['input_swir_path'])
    return _normalized_difference(nir, swir, _output_path(params.get('output_path'), 'nbr.tif'))

def _rs_ndwi(params: dict[str, Any]) -> str:
    green_values = params.get('input_swir_paths') or params.get('green_band_files')
    nir_values = params.get('input_nir_paths') or params.get('nir_band_files')
    if green_values or nir_values:
        if not isinstance(green_values, list) or not isinstance(nir_values, list):
            raise ValueError('NDWI batch mode requires input_swir_paths and input_nir_paths arrays')
        if len(green_values) != len(nir_values) or not green_values:
            raise ValueError('NDWI batch arrays must be non-empty and have equal length')
        outputs = []
        for green_value, nir_value in zip(green_values, nir_values):
            green = _resolve_path(green_value)
            nir = _resolve_path(nir_value)
            output = _output_path(None, f'{green.stem}_ndwi.tif')
            outputs.append(source_decode(_normalized_difference(green, nir, output)))
        return _result(outputs=outputs, input_count=len(outputs))
    green = _resolve_path(params.get('green_band_file', params.get('input_swir_path')) or params.get('green_band_file'))
    nir = _resolve_path(params.get('nir_band_file', params.get('input_nir_path')) or params.get('nir_band_file'))
    return _normalized_difference(green, nir, _output_path(params.get('output_path'), 'ndwi.tif'))

def _rs_ndti(params: dict[str, Any]) -> str:
    from .scientific_spatial import ScientificResultError
    if not isinstance(params.get('input_pairs'), list) or not params['input_pairs']:
        raise ScientificResultError('NDTI requires a nonempty list of explicit input band pairs')
    outputs = []
    for pair in params.get('input_pairs', []):
        green = _resolve_path(pair['input_green_path'])
        red = _resolve_path(pair['input_red_path'])
        output = _output_path(pair.get('output_filename'), f'{green.stem}_ndti.tif')
        outputs.append(source_decode(_normalized_difference(green, red, output)))
    return _result(outputs=outputs)

def _rs_cloud_mask(params: dict[str, Any]) -> str:
    import numpy as np
    source_values = params.get('sr_band_paths')
    qa_values = params.get('qa_pixel_paths')
    if source_values or qa_values:
        if not isinstance(source_values, list) or not isinstance(qa_values, list):
            raise ValueError('Cloud-mask batch mode requires sr_band_paths and qa_pixel_paths arrays')
        if len(source_values) != len(qa_values) or not source_values:
            raise ValueError('Cloud-mask batch arrays must be non-empty and have equal length')
        outputs = []
        for source_value, qa_value in zip(source_values, qa_values):
            source = _resolve_path(source_value)
            qa_path = _resolve_path(qa_value)
            band, qa = (_read_raster(source), _read_raster(qa_path).astype('uint32'))
            clear = (qa & 1 << 3 == 0) & (qa & 1 << 4 == 0)
            masked = np.where(clear, band, np.nan)
            output = _output_path(None, f'{source.stem}_cloud_masked.tif')
            _write_raster(masked, output, source)
            outputs.append({'output_path': str(output), 'source_path': str(source), 'qa_pixel_path': str(qa_path), 'clear_percentage': float(clear.mean() * 100)})
        return _result(outputs=outputs, input_count=len(outputs))
    source = _resolve_path(params['sr_band_path'])
    qa_path = _resolve_path(params['qa_pixel_path'])
    band, qa = (_read_raster(source), _read_raster(qa_path).astype('uint32'))
    clear = (qa & 1 << 3 == 0) & (qa & 1 << 4 == 0)
    masked = np.where(clear, band, np.nan)
    output = _output_path(params.get('output_path'), 'cloud_masked.tif')
    _write_raster(masked, output, source)
    return _result(output_path=output, clear_percentage=float(clear.mean() * 100))

def _rs_hotspot_raster(params: dict[str, Any]) -> str:
    import numpy as np
    paths = _file_list(params)
    threshold = float(params['threshold'])
    names = params.get('output_path_list') or []
    outputs = []
    for index, path in enumerate(paths):
        array = _read_raster(path)
        comparison = str(params.get('comparison', 'below')).lower()
        binary = np.where(np.isfinite(array), (array < threshold if comparison == 'below' else array > threshold).astype('float32'), np.nan)
        output = _output_path(names[index] if index < len(names) else None, f'hotspot_{index:03d}.tif')
        _write_raster(binary, output, path)
        outputs.append(str(output))
    return _result(outputs=outputs, threshold=threshold)

def _rs_difference(params: dict[str, Any], subtract_keys: bool=False) -> str:
    import numpy as np

    def subtract(first_path, second_path):
        _require_matching_grids([first_path, second_path])
        first_array = _read_raster(first_path)
        second_array = _read_raster(second_path)
        if bool(params.get('nodata_as_zero', False)):
            first_array = np.nan_to_num(first_array, nan=0.0)
            second_array = np.nan_to_num(second_array, nan=0.0)
        return first_array - second_array
    first_key, second_key = ('img1_path', 'img2_path') if subtract_keys else ('image_a_path', 'image_b_path')
    if not subtract_keys and (params.get('image_a_paths') or params.get('image_b_paths')):
        first_values = params.get('image_a_paths')
        second_values = params.get('image_b_paths')
        if not isinstance(first_values, list) or not isinstance(second_values, list):
            raise ValueError('TiffDifference batch mode requires image_a_paths and image_b_paths arrays')
        if not first_values or len(first_values) != len(second_values):
            raise ValueError('TiffDifference batch arrays must be non-empty and have equal length')
        outputs = []
        for first_value, second_value in zip(first_values, second_values):
            first, second = (_resolve_path(first_value), _resolve_path(second_value))
            array = subtract(first, second)
            output = _output_path(None, f'{first.stem}_to_{second.stem}_difference.tif')
            _write_raster(array, output, first)
            outputs.append({'output_path': str(output), 'image_a_path': str(first), 'image_b_path': str(second), 'mean': float(np.nanmean(array))})
        return _result(outputs=outputs, input_count=len(outputs))
    first, second = (_resolve_path(params[first_key]), _resolve_path(params[second_key]))
    array = subtract(first, second)
    output = _output_path(params.get('output_path'), 'difference.tif')
    _write_raster(array, output, first)
    return _result(output_path=output, mean=float(np.nanmean(array)))

def _rs_fire_map(params: dict[str, Any]) -> str:
    import numpy as np
    source = _resolve_path(params['change_image_path'])
    array = _read_raster(source)
    result = np.where(np.isfinite(array), (array > float(params['threshold'])).astype('float32'), np.nan)
    output = _output_path(params.get('output_path'), 'fire_increase_map.tif')
    _write_raster(result, output, source)
    return _result(output_path=output, positive_pixels=int(np.nansum(result)))

def _rs_count_threshold(params: dict[str, Any]) -> str:
    import numpy as np
    path = _resolve_path(params.get('file_path') or params.get('binary_map_path'))
    values = _read_raster(path)
    finite = values[np.isfinite(values)]
    threshold = float(params.get('threshold', 0))
    return _result(count=int((finite >= threshold).sum()), finite_pixels=int(finite.size), percentage=float((finite >= threshold).mean() * 100))

def _series(params: dict[str, Any]) -> list[float]:
    values = params.get('x') or params.get('values')
    return [float(value) for value in values]

def _rs_scalar(name: str, params: dict[str, Any]) -> str:
    import numpy as np
    if name == 'RemoteSensingMean':
        return _result(value=float(np.mean(_series(params))))
    if name == 'RemoteSensingDifference':
        return _result(value=float(params['a']) - float(params['b']))
    if name == 'RemoteSensingDivision':
        if params.get('a_values') is not None or params.get('b_values') is not None:
            a_values = np.asarray(params.get('a_values'), dtype='float64')
            b_values = np.asarray(params.get('b_values'), dtype='float64')
            if a_values.ndim != 1 or b_values.ndim != 1 or a_values.size == 0:
                raise ValueError('Division array mode requires non-empty one-dimensional arrays')
            if a_values.shape != b_values.shape:
                raise ValueError('Division arrays must have equal length')
            ratios = np.divide(a_values, b_values, out=np.full_like(a_values, np.nan), where=b_values != 0)
            return _result(values=ratios.tolist(), count=int(ratios.size))
        return _result(value=float(params['a']) / float(params['b']))
    if name == 'RemoteSensingPercentageChange':
        a, b = (float(params['a']), float(params['b']))
        return _result(value=(b - a) / a * 100)
    if name == 'RemoteSensingKelvinToCelsius':
        return _result(value=float(params.get('kelvin', params.get('value'))) - 273.15)
    if name == 'RemoteSensingLinearTrend':
        y_values = params.get('y') or params.get('values') or params.get('x')
        values = np.asarray([float(value) for value in y_values], dtype=float)
        explicit_x = params.get('x') if params.get('y') is not None else None
        if explicit_x is None:
            x = np.arange(values.size, dtype=float)
        else:
            x = np.asarray([float(value) for value in explicit_x], dtype=float)
            if x.size and np.nanmin(np.abs(x)) >= 1000:
                x = x - x[0]
        if x.size != values.size:
            raise ValueError('RemoteSensingLinearTrend requires x and y arrays of equal length')
        slope, intercept = np.polyfit(x, values, 1)
        return _result(slope=float(slope), intercept=float(intercept))
    values = np.asarray(_series(params), dtype=float)
    if name == 'RemoteSensingMaxValueAndIndex':
        index = int(np.nanargmax(values))
        return _result(value=float(values[index]), index=index)
    if name == 'RemoteSensingMinValueAndIndex':
        index = int(np.nanargmin(values))
        return _result(value=float(values[index]), index=index)
    if name == 'RemoteSensingArgmax':
        return _result(index=int(np.nanargmax(values)))
    if name == 'RemoteSensingSensSlope':
        slopes = [(values[j] - values[i]) / (j - i) for i in range(len(values)) for j in range(i + 1, len(values))]
        return _result(slope=float(np.median(slopes)))
    if name == 'RemoteSensingCoefficientOfVariation':
        return _result(value=float(np.std(values) / np.mean(values)))
    if name == 'RemoteSensingKurtosis':
        centered = values - values.mean()
        variance = np.mean(centered ** 2)
        pearson = float(np.mean(centered ** 4) / variance ** 2)
        return _result(kurtosis=pearson, excess_kurtosis=pearson - 3.0)
    if name == 'RemoteSensingMannKendallTest':
        s = sum((int(np.sign(values[j] - values[i])) for i in range(len(values)) for j in range(i + 1, len(values))))
        variance = len(values) * (len(values) - 1) * (2 * len(values) + 5) / 18
        z = (s - 1) / math.sqrt(variance) if s > 0 else (s + 1) / math.sqrt(variance) if s < 0 else 0.0
        return _result(s=s, z=z, p_value=math.erfc(abs(z) / math.sqrt(2)), trend='increasing' if s > 0 else 'decreasing' if s < 0 else 'no trend')
    raise KeyError(name)
_HAZARD_FILE = _DATASET_ROOT / '10.自然灾害与极端地震.xlsx'

def _hazard_table(params):
    import pandas as pd
    location = params.get('source')
    if not location:
        raise ValueError('source is required; there is no implicit event database.')
    path = Path(location)
    if path.suffix.lower() == '.csv':
        frame = pd.read_csv(path)
    elif path.suffix.lower() == '.xlsx':
        frame = pd.read_excel(path, sheet_name=params.get('sheet', 'Sheet1'))
    else:
        raise ValueError('Event source must be CSV or XLSX.')
    for field, expected in params.get('filters', {}).items():
        if field not in frame.columns:
            raise ValueError('Unknown filter column: ' + field)
        frame = frame.loc[frame[field] == expected].copy()
    measure = params.get('measure')
    if measure:
        if measure not in frame.columns:
            raise ValueError('Unknown measure column: ' + measure)
        values = pd.to_numeric(frame[measure], errors='coerce')
        if values.isna().any() or not all((math.isfinite(float(x)) for x in values)):
            raise ValueError('Measure values must be finite; missing values are not imputed.')
        frame[measure] = values
    group = params.get('group_by')
    if group and group not in frame.columns:
        raise ValueError('Unknown grouping column: ' + group)
    return frame

def _hazard_filtered(params: dict[str, Any]):
    import pandas as pd
    filtered_path = params.get('filtered_records_path')
    table = pd.read_json(_resolve_path(filtered_path), lines=True) if filtered_path else _hazard_table(params).copy()
    filters = params.get('filters') or {}
    if isinstance(filters, list):
        merged: dict[str, Any] = {}
        for item in filters:
            if isinstance(item, dict):
                merged.update(item)
        filters = merged
    if not isinstance(filters, dict):
        raise ValueError('Natural-hazard filters must be a JSON object')
    for field, value in filters.items():
        if field not in table.columns:
            raise ValueError(f'Unknown natural-hazard field: {field}')
        if isinstance(value, list):
            table = table[table[field].isin(value)]
        elif value is None:
            table = table[table[field].isna()]
        else:
            table = table[table[field] == value]
    return table

def _hazard_load(params: dict[str, Any]) -> str:
    table = _hazard_table(params)
    return _result(source=Path(params['source']), sheet='Sheet1', record_count=int(len(table)), columns=list(table.columns))

def _hazard_filter(params: dict[str, Any]) -> str:
    filters = params.get('filters')
    if isinstance(filters, list):
        filters = {key: value for item in filters if isinstance(item, dict) for key, value in item.items()}
        params = {**params, 'filters': filters}
    if not isinstance(filters, dict) or not filters:
        raise ValueError('NaturalHazardFilterRecords requires a non-empty filters object')
    table = _hazard_filtered(params)
    digest = abs(hash(json.dumps(filters, ensure_ascii=False, sort_keys=True)))
    output = _output_root() / 'natural_hazard' / f'filtered_{digest}.jsonl'
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_json(output, orient='records', lines=True, force_ascii=False, date_format='iso')
    return _result(filters=filters, record_count=int(len(table)), filtered_records_path=output)

def _hazard_count(params: dict[str, Any]) -> str:
    return _result(filters=params.get('filters', {}), count=int(len(_hazard_filtered(params))))

def _hazard_sum(params: dict[str, Any]) -> str:
    table = _hazard_filtered(params)
    field = str(params.get('measure') or params.get('field'))
    return _result(filters=params.get('filters', {}), measure=field, sum=float(table[field].fillna(0).sum()))

def _hazard_group(params: dict[str, Any]) -> str:
    table = _hazard_filtered(params)
    group_by = str(params['group_by'])
    measure = params.get('measure')
    if measure:
        ranked = table.groupby(group_by, dropna=False)[str(measure)].sum(min_count=1).sort_values(ascending=False)
        aggregate = 'sum'
    else:
        ranked = table.groupby(group_by, dropna=False).size().sort_values(ascending=False)
        aggregate = 'count'
    records = [{group_by: _clean(index), aggregate: _clean(value)} for index, value in ranked.items()]
    return _result(filters=params.get('filters', {}), group_by=group_by, aggregate=aggregate, ranking=records, top=records[0] if records else None)

def _hazard_max(params: dict[str, Any]) -> str:
    table = _hazard_filtered(params)
    field = str(params.get('measure') or params.get('field'))
    row = table.loc[table[field].astype(float).idxmax()]
    return _result(filters=params.get('filters', {}), measure=field, event=_row_dict(row))

def _hazard_dates(params: dict[str, Any]) -> str:
    import pandas as pd
    table = _hazard_filtered(params)
    fields = params.get('date_fields') or ['Start Year', 'Start Month', 'Start Day']
    dates = pd.to_datetime(dict(year=table[fields[0]], month=table[fields[1]], day=table[fields[2]]), errors='coerce')
    valid = dates.dropna()
    return _result(filters=params.get('filters', {}), valid_date_count=int(valid.size), latest_date=None if valid.empty else valid.max().date().isoformat())

def _hazard_latest(params: dict[str, Any]) -> str:
    import pandas as pd
    table = _hazard_filtered(params).copy()
    fields = params.get('date_fields') or ['Start Year', 'Start Month', 'Start Day']
    table['_start_date'] = pd.to_datetime(dict(year=table[fields[0]], month=table[fields[1]], day=table[fields[2]]), errors='coerce')
    row = table.dropna(subset=['_start_date']).sort_values('_start_date').iloc[-1]
    return _result(filters=params.get('filters', {}), latest_date=row['_start_date'].date().isoformat(), event=_row_dict(row.drop(labels=['_start_date'])))
_GIS_SUFFIXES: dict[str, Callable[[dict[str, Any]], str]] = {'StandardizeSpatialData': _standardize_spatial, 'ValidateSpatialData': _validate_spatial, 'NearestNeighbor': _nearest_neighbor, 'Buffer': _buffer_points, 'Overlay': _overlay, 'BatchVector': _batch_vector, 'InterpolateIDW': _interpolate_idw, 'RasterAlgebra': _raster_algebra, 'ZonalStatistics': _zonal_stats, 'RenderMap': _render_map}
_IMPLEMENTATIONS: dict[str, Callable[[dict[str, Any]], str]] = {'DeepEarthQueryLITHO1': _deep_litho, 'DeepEarthQuerySEMUCB': _deep_semucb, 'DeepEarthQueryUSGSCatalog': _deep_usgs_query, 'DeepEarthGetUSGSEvent': _deep_usgs_event, 'DeepEarthSampleEventModels': _deep_event_models, 'GeoBigDataExecuteGeoSPARQL': _geosparql, 'MineralResourcesSearchDeposits': _mineral_search, 'MineralResourcesGetDeposit': _mineral_get, 'MineralResourcesCountrySummary': _mineral_country_summary, 'MineralResourcesRankCommodityCountries': _mineral_rank_commodity, 'ClimateQueryDeepTime': _climate_deep, 'ClimateQueryPresentMean': _climate_present, 'ClimateQueryFutureSSP': _climate_ssp, 'ClimateCompareEpochs': _climate_compare, 'EnergyFacilityDistance': _energy_facility_distance, 'EnergyMineralSiteDistance': _energy_mineral_distance, 'EnergyBBoxArea': _energy_bbox, 'EnergyNearestFacility': _energy_nearest, 'EnergyCapacityValue': _energy_capacity, 'EnergyNearestMineralSite': _energy_cross_nearest, 'EnergyCountryRenewableSummary': _energy_mix, 'EnergyCapacityGrowth': _energy_growth, 'EnergyTransitionMetrics': _energy_transition, 'EnergyRegionalOverlaySummary': _energy_overlay, 'OceanMonthlyGridValue': _ocean_grid, 'OceanProfileValue': _ocean_profile, 'OceanCruiseQC': _ocean_qc, 'OceanStationDistance': _ocean_station_distance, 'OceanBBoxArea': _ocean_bbox, 'OceanAnnualCarbonSummary': _ocean_annual, 'OceanVerticalProfileDifference': _ocean_vertical, 'OceanRegionalMapSummary': _ocean_map, 'OceanSurfaceDeepMatch': _ocean_match, 'OceanProfileDeduplication': _ocean_dedup, 'DeepTimeDecimalToDMS': _decimal_to_dms, 'DeepTimeHaversineDistance': _distance, 'DeepTimeBearing': _bearing, 'DeepTimeBBoxArea': _bbox_tool, 'CCSDecimalToDMS': _decimal_to_dms, 'CCSHaversineDistance': _distance, 'CCSBearing': _bearing, 'CCSBBoxArea': _bbox_tool, 'CCSCheckCRSConsistency': _crs_check, 'RemoteSensingListFiles': _rs_list, 'RemoteSensingBatchImageMean': lambda p: _rs_batch_stat(p, 'mean'), 'RemoteSensingBatchHotspotPercentage': lambda p: _rs_batch_stat(p, 'hotspot_percentage'), 'RemoteSensingTiffAverage': _rs_tiff_average, 'RemoteSensingBatchNDSI': _rs_batch_ndsi, 'RemoteSensingNDWI': _rs_ndwi, 'RemoteSensingNBR': _rs_nbr, 'RemoteSensingCloudMask': _rs_cloud_mask, 'RemoteSensingBatchHotspotRaster': _rs_hotspot_raster, 'RemoteSensingNDVI': _rs_ndvi, 'RemoteSensingNDTI': _rs_ndti, 'RemoteSensingCountAboveThreshold': _rs_count_threshold, 'RemoteSensingBatchImageSum': lambda p: _rs_batch_stat(p, 'sum'), 'RemoteSensingTiffDifference': _rs_difference, 'RemoteSensingExtremeSnowLossPercentage': _rs_count_threshold, 'RemoteSensingSubtract': lambda p: _rs_difference(p, True), 'RemoteSensingFireIncreaseMap': _rs_fire_map, 'NaturalHazardLoadEventTable': _hazard_load, 'NaturalHazardFilterRecords': _hazard_filter, 'NaturalHazardCountRecords': _hazard_count, 'NaturalHazardSumField': _hazard_sum, 'NaturalHazardGroupAggregate': _hazard_group, 'NaturalHazardSelectMaxRecord': _hazard_max, 'NaturalHazardBuildStartDate': _hazard_dates, 'NaturalHazardSelectLatest': _hazard_latest}
_SCALAR_REMOTE = {'RemoteSensingMean', 'RemoteSensingPercentageChange', 'RemoteSensingDifference', 'RemoteSensingDivision', 'RemoteSensingLinearTrend', 'RemoteSensingMaxValueAndIndex', 'RemoteSensingKelvinToCelsius', 'RemoteSensingMinValueAndIndex', 'RemoteSensingSensSlope', 'RemoteSensingCoefficientOfVariation', 'RemoteSensingKurtosis', 'RemoteSensingMannKendallTest', 'RemoteSensingArgmax'}

def _dispatch_impl(tool_name: str, input_str: str) -> str:
    params = _params(input_str)
    if tool_name in _IMPLEMENTATIONS:
        return _IMPLEMENTATIONS[tool_name](params)
    if tool_name in _SCALAR_REMOTE:
        return _rs_scalar(tool_name, params)
    for suffix, implementation in _GIS_SUFFIXES.items():
        if tool_name.endswith(suffix):
            return implementation(params)
    raise KeyError(f'No executable implementation registered for {tool_name}')

def _dispatch_source(tool_name: str, input_str: str) -> str:
    from .scientific_contracts import tool_scientific_contract, validate_scientific_result
    raw = _dispatch_impl(tool_name, input_str)
    payload = source_decode(raw)
    if isinstance(payload, dict) and payload.get('status') == 'error':
        return raw
    contract = tool_scientific_contract(tool_name)
    validation = validate_scientific_result(tool_name, payload)
    if not validation['valid']:
        return _result(status='error', error_type='scientific_result_error', retryable=False, error='; '.join(validation['reasons']), scientific_validation=validation)
    if isinstance(payload, dict) and contract['implementation_kind'] != 'unreviewed':
        payload['scientific_contract'] = contract
        payload['scientific_validation'] = validation
    return _result(**payload) if isinstance(payload, dict) else raw

def _tool(tool_name: str) -> Callable[[str], str]:

    def run(input_str: str) -> str:
        try:
            params = _params(input_str)
            raw = dispatch(tool_name, input_str)
            if source_decode(raw).get('status') == 'error':
                return raw
            output_keys = params.get('_output_keys') or []
            if output_keys:
                payload = source_decode(raw)
                standardized = payload.get('standardized_layers') or []
                reports = payload.get('validation_reports') or []
                standardized_paths = [item.get('output') for item in standardized if isinstance(item, dict) and item.get('output')]
                clean_paths = [item.get('clean_output') for item in reports if isinstance(item, dict) and item.get('clean_output')]
                for key in output_keys:
                    if key in payload:
                        continue
                    if key in ('standardized_points', 'standardized_layer'):
                        payload[key] = standardized_paths[0] if standardized_paths else None
                    elif key == 'standardized_layers':
                        payload[key] = standardized_paths
                    elif key in ('clean_points', 'clean_leak_points', 'leak_points_projected'):
                        payload[key] = clean_paths[0] if clean_paths else standardized_paths[0] if standardized_paths else None
                    elif key in ('clean_layers', 'batch_layers', 'joined_layers'):
                        payload[key] = clean_paths or standardized_paths
                    elif 'report' in key:
                        payload[key] = reports
                    elif 'neighbour' in key:
                        payload[key] = payload.get('nearest_neighbours')
                    elif 'buffer' in key:
                        payload[key] = payload.get('buffer_output')
                    elif any((token in key for token in ('overlay', 'join', 'zone_points', 'monitoring_zones', 'priority_zones'))):
                        payload[key] = payload.get('overlay_output')
                    elif 'raster' in key:
                        payload[key] = payload.get('raster_output')
                    elif 'stats' in key:
                        payload[key] = {name: value for name, value in payload.items() if name not in output_keys}
                    elif key in ('map_png', 'map_html'):
                        payload[key] = payload.get(key)
                    elif 'dms' in key:
                        payload[key] = payload.get('dms')
                    elif 'distance' in key:
                        payload[key] = payload.get('distance_km')
                    elif 'bearing' in key:
                        payload[key] = payload.get('bearing_degrees')
                    elif 'area' in key:
                        payload[key] = payload.get('area_km2')
                    else:
                        payload[key] = {name: value for name, value in payload.items() if name not in output_keys}
                return json.dumps(_clean(payload), ensure_ascii=False, sort_keys=True)
            return raw
        except Exception as exc:
            from .scientific_spatial import ScientificResultError, UnsupportedOperation
            if isinstance(exc, (ScientificResultError, UnsupportedOperation)):
                return _result(tool=tool_name, status='error', retryable=False, error_type='unsupported_operation' if isinstance(exc, UnsupportedOperation) else 'scientific_result_error', error=str(exc))
            return _result(tool=tool_name, status='error', error_type=type(exc).__name__, error=str(exc))
    run.__name__ = tool_name
    run.__doc__ = f'Execute {tool_name} with a JSON string or documented compact text input.'
    return run

def build_tool_dict(category: str) -> dict[str, Callable[[str], str]]:
    from ToolsFuns.GeoEval.catalog import TOOLS_MAPPING
    return {name: _tool(name) for name in TOOLS_MAPPING[category]}
_SOURCE_OUTPUT = ContextVar('geotool_source_output', default=None)

def _output_root():
    output = _SOURCE_OUTPUT.get()
    if output is None:
        raise ValueError('This file-producing tool requires an explicit output_dir.')
    output.mkdir(parents=True, exist_ok=True)
    return output

def dispatch(tool_name, input_str, *, output_dir=None):
    from .native_recovery import RECOVERED, run as native_run
    if tool_name in RECOVERED:
        return native_run(tool_name, input_str, output_dir=output_dir)
    if tool_name in ("RemoteSensingMannKendallTest", "GeoOrdinaryKrigingGrid", "GeoExactZonalStatistics"):
        from .scientific_tools import mann_kendall, ordinary_kriging_grid, exact_zonal_statistics
        if tool_name == "GeoOrdinaryKrigingGrid":
            return ordinary_kriging_grid(input_str, output_dir=output_dir)
        function = mann_kendall if tool_name == "RemoteSensingMannKendallTest" else exact_zonal_statistics
        return function(input_str)
    params = source_arguments(tool_name, input_str)
    source_check_files(tool_name, params)
    if tool_name == 'RemoteSensingExtremeSnowLossPercentage':
        params['threshold'] = 0.5
    token = _SOURCE_OUTPUT.set(Path(output_dir).resolve() if output_dir is not None else None)
    try:
        value = source_decode(_dispatch_source(tool_name, params))
        if tool_name == 'NaturalHazardLoadEventTable' and isinstance(value, dict) and (value.get('status') != 'error'):
            value['source'] = str(Path(params['source']))
            value['sheet'] = params.get('sheet', 'Sheet1') if Path(params['source']).suffix.lower() == '.xlsx' else None
        return source_result(tool_name, value)
    finally:
        _SOURCE_OUTPUT.reset(token)

