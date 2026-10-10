import uuid
from pathlib import Path
from ..source_contracts import arguments as source_arguments, result as source_result, check_files as source_check_files
import argparse
import csv
import html
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import requests
try:
    import pandas as pd
except ImportError:
    pd = None
try:
    import folium
except ImportError:
    folium = None
USGS_EVENT_API = 'https://earthquake.usgs.gov/fdsnws/event/1/query'
GEO_TEMP_DIR = Path(__file__).resolve().parents[2] / 'TempFiles' / 'GeoToolKG'

def _ensure_geo_temp_dir() -> Path:
    GEO_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return GEO_TEMP_DIR

def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')

def _parse_key_value_args(input_text: str) -> dict:
    text = (input_text or '').strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {str(key).strip(): str(value).strip() for key, value in parsed.items()}
    except json.JSONDecodeError:
        pass
    params = {}
    for part in re.split('[,;\\n]+', text):
        part = part.strip()
        if not part:
            continue
        if '=' in part:
            key, value = part.split('=', 1)
        elif ':' in part:
            key, value = part.split(':', 1)
        else:
            continue
        key = key.strip().lstrip('-')
        value = value.strip().strip('\'"')
        if key:
            params[key] = value
    return params

def _extract_existing_path(input_text: str, suffix: str) -> str:
    text = (input_text or '').strip().strip('\'"')
    if text and Path(text).exists() and text.lower().endswith(suffix):
        return text
    pattern = f"""([A-Za-z]:[^\\n\\r`\\"']+?\\.{re.escape(suffix.lstrip('.'))})"""
    match = re.search(pattern, input_text or '', flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip()
        if Path(candidate).exists():
            return candidate
    pattern = f"""([^\\s`\\"']+?\\.{re.escape(suffix.lstrip('.'))})"""
    for match in re.finditer(pattern, input_text or '', flags=re.IGNORECASE):
        candidate = match.group(1).strip()
        if Path(candidate).exists():
            return candidate
    return ''

def _latest_file(pattern: str) -> str:
    temp_dir = _ensure_geo_temp_dir()
    files = sorted(temp_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ''

def _markdown_path(label: str, path: str) -> str:
    return f'{label}: {Path(path).resolve()}'

def _classify_magnitude(magnitude) -> tuple:
    try:
        mag = float(magnitude)
    except (TypeError, ValueError):
        return ('Unknown', 0, '#7f8c8d')
    if mag < 2.0:
        return ('Micro', 1, '#2ecc71')
    if mag < 4.0:
        return ('Minor', 2, '#8bc34a')
    if mag < 5.0:
        return ('Light', 3, '#f1c40f')
    if mag < 6.0:
        return ('Moderate', 4, '#e67e22')
    if mag < 7.0:
        return ('Strong', 5, '#e74c3c')
    if mag < 8.0:
        return ('Major', 6, '#9b59b6')
    return ('Great', 7, '#6c1d45')

def _read_csv_rows(csv_path: str) -> list:
    with open(csv_path, newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))

def _write_csv_rows(csv_path: str, rows: list, fieldnames: list) -> None:
    with open(csv_path, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def _coerce_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result

from ..GeoEval.native_recovery import usgs_earthquake_data_fetch, visualize_earthquake_event_map

def _clean_with_pandas(input_path: str, output_path: str) -> tuple:
    df = pd.read_csv(input_path)
    required = ['time', 'latitude', 'longitude', 'depth', 'mag']
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    before_count = len(df)
    for column in ['latitude', 'longitude', 'depth', 'mag']:
        df[column] = pd.to_numeric(df[column], errors='coerce')
    df['time'] = pd.to_datetime(df['time'], errors='coerce', utc=True)
    df = df.dropna(subset=required)
    df = df[df['latitude'].between(-90, 90) & df['longitude'].between(-180, 180) & df['depth'].between(-10, 1000) & df['mag'].between(-2, 10)]
    if 'type' in df.columns:
        df = df[df['type'].fillna('').str.lower().eq('earthquake')]
    if 'id' in df.columns:
        df = df.drop_duplicates(subset=['id'], keep='first')
    else:
        df = df.drop_duplicates(subset=['time', 'latitude', 'longitude', 'mag'], keep='first')
    classifications = df['mag'].apply(_classify_magnitude)
    df['magnitude_class'] = classifications.apply(lambda item: item[0])
    df['magnitude_level'] = classifications.apply(lambda item: item[1])
    df['marker_color'] = classifications.apply(lambda item: item[2])
    if 'place' not in df.columns:
        df['place'] = 'Unknown'
    df['place'] = df['place'].fillna('Unknown')
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    df = df.sort_values(['magnitude_level', 'mag'], ascending=[False, False])
    df.to_csv(output_path, index=False, encoding='utf-8')
    return (before_count, len(df))

def _clean_with_stdlib(input_path: str, output_path: str) -> tuple:
    rows = _read_csv_rows(input_path)
    if not rows:
        raise ValueError('Input CSV has no earthquake rows.')
    required = ['time', 'latitude', 'longitude', 'depth', 'mag']
    missing = [column for column in required if column not in rows[0]]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    cleaned = []
    seen = set()
    for row in rows:
        latitude = _coerce_float(row.get('latitude'))
        longitude = _coerce_float(row.get('longitude'))
        depth = _coerce_float(row.get('depth'))
        magnitude = _coerce_float(row.get('mag'))
        event_time = (row.get('time') or '').strip()
        if None in (latitude, longitude, depth, magnitude) or not event_time:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        if not (-10 <= depth <= 1000 and -2 <= magnitude <= 10):
            continue
        if row.get('type') and row.get('type', '').strip().lower() != 'earthquake':
            continue
        dedupe_key = row.get('id') or f'{event_time}|{latitude}|{longitude}|{magnitude}'
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        label, level, color = _classify_magnitude(magnitude)
        row['latitude'] = f'{latitude:.6f}'
        row['longitude'] = f'{longitude:.6f}'
        row['depth'] = f'{depth:.3f}'
        row['mag'] = f'{magnitude:.3f}'
        row['place'] = row.get('place') or 'Unknown'
        row['magnitude_class'] = label
        row['magnitude_level'] = str(level)
        row['marker_color'] = color
        cleaned.append(row)
    cleaned.sort(key=lambda item: (int(item['magnitude_level']), float(item['mag'])), reverse=True)
    fieldnames = list(rows[0].keys())
    for column in ['magnitude_class', 'magnitude_level', 'marker_color']:
        if column not in fieldnames:
            fieldnames.append(column)
    _write_csv_rows(output_path, cleaned, fieldnames)
    return (len(rows), len(cleaned))

def clean_and_classify_earthquake_data(input_str, *, output_dir=None):
    """Clean explicit caller data and return typed results, not a Markdown status."""
    params = source_arguments('地震数据清洗与分级', input_str)
    source_check_files('地震数据清洗与分级', params)
    if output_dir is None:
        raise ValueError('An explicit output_dir is required.')
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / ('earthquakes-' + uuid.uuid4().hex + '.csv')
    before, after = _clean_with_pandas(params['source'], str(output))
    return source_result('地震数据清洗与分级', {'output_path': str(output), 'input_rows': int(before), 'clean_rows': int(after), 'dropped_rows': int(before - after)})

def _load_points(csv_path: str) -> list:
    rows = _read_csv_rows(csv_path)
    points = []
    for row in rows:
        latitude = _coerce_float(row.get('latitude'))
        longitude = _coerce_float(row.get('longitude'))
        magnitude = _coerce_float(row.get('mag'))
        depth = _coerce_float(row.get('depth'))
        if None in (latitude, longitude, magnitude, depth):
            continue
        label, level, color = _classify_magnitude(magnitude)
        points.append({'time': row.get('time', ''), 'latitude': latitude, 'longitude': longitude, 'depth': depth, 'mag': magnitude, 'place': row.get('place') or 'Unknown', 'magnitude_class': row.get('magnitude_class') or label, 'magnitude_level': int(row.get('magnitude_level') or level), 'marker_color': row.get('marker_color') or color, 'id': row.get('id', '')})
    return points

def _legend_html() -> str:
    items = [('Micro <2', '#2ecc71'), ('Minor 2-3.9', '#8bc34a'), ('Light 4-4.9', '#f1c40f'), ('Moderate 5-5.9', '#e67e22'), ('Strong 6-6.9', '#e74c3c'), ('Major 7-7.9', '#9b59b6'), ('Great >=8', '#6c1d45')]
    rows = ''.join((f"<div><span style='display:inline-block;width:12px;height:12px;background:{color};border-radius:50%;margin-right:6px'></span>{label}</div>" for label, color in items))
    return f"<div style='position: fixed; bottom: 24px; left: 24px; z-index: 9999; background: white; padding: 12px 14px; border: 1px solid #999; box-shadow: 0 2px 8px rgba(0,0,0,.18); font-size: 13px;'><strong>Magnitude classes</strong>{rows}</div>"

def _map_css() -> str:
    return '\n<style>\n  .earthquake-mag-label {\n    background: rgba(17, 24, 39, 0.88);\n    border: 1px solid rgba(255, 255, 255, 0.85);\n    border-radius: 999px;\n    box-shadow: 0 1px 4px rgba(0, 0, 0, 0.24);\n    color: #fff;\n    font: 700 11px/1.1 Arial, sans-serif;\n    min-width: 30px;\n    padding: 3px 6px;\n    pointer-events: none;\n    text-align: center;\n    transform: translate(10px, -24px);\n    white-space: nowrap;\n  }\n  .earthquake-count-panel {\n    position: fixed;\n    right: 24px;\n    top: 24px;\n    z-index: 9999;\n    background: white;\n    border: 1px solid #999;\n    box-shadow: 0 2px 8px rgba(0,0,0,.18);\n    color: #1f2933;\n    font: 13px/1.45 Arial, sans-serif;\n    padding: 10px 12px;\n  }\n</style>\n'

def _count_panel_html(point_count: int) -> str:
    return f"<div class='earthquake-count-panel'><strong>Earthquake events rendered</strong><br>{point_count} epicenters / {point_count} magnitude labels</div>"

def _marker_radius(magnitude: float) -> float:
    return max(4, min(18, magnitude * 2.2))

def _bounds(points: list) -> list:
    return [[point['latitude'], point['longitude']] for point in points]

def _render_with_folium(points: list, output_path: str) -> None:
    if points:
        center_lat = sum((point['latitude'] for point in points)) / len(points)
        center_lon = sum((point['longitude'] for point in points)) / len(points)
    else:
        center_lat, center_lon = (20.0, 0.0)
    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=2, tiles='CartoDB positron', control_scale=True)
    folium.TileLayer('OpenStreetMap', name='OpenStreetMap').add_to(fmap)
    marker_layer = folium.FeatureGroup(name='Epicenters', show=True)
    label_layer = folium.FeatureGroup(name='Magnitude labels', show=True)
    for point in points:
        radius = _marker_radius(point['mag'])
        popup_html = f"<div style='min-width:220px'><strong>{html.escape(point['place'])}</strong><br>Time: {html.escape(point['time'])}<br>Magnitude: {point['mag']:.2f} ({html.escape(point['magnitude_class'])})<br>Depth: {point['depth']:.1f} km<br>ID: {html.escape(point['id'])}</div>"
        folium.CircleMarker(location=[point['latitude'], point['longitude']], radius=radius, color='#2c3e50', weight=1, fill=True, fill_color=point['marker_color'], fill_opacity=0.78, popup=folium.Popup(popup_html, max_width=320), tooltip=f"M{point['mag']:.1f} | {point['magnitude_class']} | {point['place']}").add_to(marker_layer)
        label_html = f"<div class='earthquake-mag-label' title='{html.escape(point['place'], quote=True)}'>M{point['mag']:.1f}</div>"
        folium.Marker(location=[point['latitude'], point['longitude']], icon=folium.DivIcon(html=label_html, icon_size=(48, 18), icon_anchor=(0, 0))).add_to(label_layer)
    marker_layer.add_to(fmap)
    label_layer.add_to(fmap)
    if points:
        fmap.fit_bounds(_bounds(points), padding=(36, 36))
    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.get_root().html.add_child(folium.Element(_map_css()))
    fmap.get_root().html.add_child(folium.Element(_legend_html()))
    fmap.get_root().html.add_child(folium.Element(_count_panel_html(len(points))))
    fmap.save(output_path)

def _render_fallback_html(points: list, output_path: str) -> None:
    points_json = json.dumps(points, ensure_ascii=False)
    document = f"""<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n  <title>Earthquake Event Map</title>\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">\n  <style>\n    html, body, #map {{ height: 100%; margin: 0; }}\n    .legend {{ position: fixed; bottom: 24px; left: 24px; z-index: 9999; background: #fff;\n      padding: 12px 14px; border: 1px solid #999; box-shadow: 0 2px 8px rgba(0,0,0,.18);\n      font: 13px/1.45 Arial, sans-serif; }}\n    .legend span {{ display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:6px; }}\n    .earthquake-mag-label {{\n      background: rgba(17, 24, 39, 0.88); border: 1px solid rgba(255, 255, 255, 0.85);\n      border-radius: 999px; box-shadow: 0 1px 4px rgba(0,0,0,.24); color: #fff;\n      font: 700 11px/1.1 Arial, sans-serif; min-width: 30px; padding: 3px 6px;\n      pointer-events: none; text-align: center; transform: translate(10px, -24px);\n      white-space: nowrap;\n    }}\n    .earthquake-count-panel {{\n      position: fixed; right: 24px; top: 24px; z-index: 9999; background: #fff;\n      border: 1px solid #999; box-shadow: 0 2px 8px rgba(0,0,0,.18);\n      color: #1f2933; font: 13px/1.45 Arial, sans-serif; padding: 10px 12px;\n    }}\n  </style>\n</head>\n<body>\n  <div id="map"></div>\n  {_legend_html()}\n  {_count_panel_html(len(points))}\n  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>\n  <script>\n    const points = {points_json};\n    const map = L.map('map').setView(points.length ? [points[0].latitude, points[0].longitude] : [20, 0], 2);\n    L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{\n      maxZoom: 18,\n      attribution: '&copy; OpenStreetMap contributors'\n    }}).addTo(map);\n    const bounds = [];\n    for (const p of points) {{\n      const radius = Math.max(4, Math.min(18, p.mag * 2.2));\n      const marker = L.circleMarker([p.latitude, p.longitude], {{\n        radius,\n        color: '#2c3e50',\n        weight: 1,\n        fillColor: p.marker_color,\n        fillOpacity: 0.78\n      }}).addTo(map);\n      marker.bindPopup(`<strong>${{p.place}}</strong><br>Time: ${{p.time}}<br>Magnitude: ${{p.mag.toFixed(2)}} (${{p.magnitude_class}})<br>Depth: ${{p.depth.toFixed(1)}} km<br>ID: ${{p.id || ''}}`);\n      marker.bindTooltip(`M${{p.mag.toFixed(1)}} | ${{p.magnitude_class}} | ${{p.place}}`);\n      L.marker([p.latitude, p.longitude], {{\n        icon: L.divIcon({{\n          className: '',\n          html: `<div class="earthquake-mag-label" title="${{p.place}}">M${{p.mag.toFixed(1)}}</div>`,\n          iconSize: [48, 18],\n          iconAnchor: [0, 0]\n        }})\n      }}).addTo(map);\n      bounds.push([p.latitude, p.longitude]);\n    }}\n    if (bounds.length) map.fitBounds(bounds, {{ padding: [24, 24] }});\n  </script>\n</body>\n</html>\n"""
    Path(output_path).write_text(document, encoding='utf-8')

def main() -> int:
    parser = argparse.ArgumentParser(description='GeoToolKG earthquake analysis tools')
    parser.add_argument('tool', choices=['fetch', 'clean', 'map'])
    parser.add_argument('input', nargs='?', default='')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    if args.tool == 'fetch':
        print(usgs_earthquake_data_fetch(args.input, output_dir=args.output_dir))
    elif args.tool == 'clean':
        print(clean_and_classify_earthquake_data(args.input, output_dir=args.output_dir))
    else:
        print(visualize_earthquake_event_map(args.input, output_dir=args.output_dir))
    return 0
if __name__ == '__main__':
    sys.exit(main())
