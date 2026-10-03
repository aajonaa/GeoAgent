"""Synthetic fixtures and result checks, not scientific ground truth."""
import csv
import hashlib
import json
import math
from pathlib import Path

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def create(workspace):
    import numpy as np
    import pandas as pd
    import rasterio
    from rasterio.transform import from_origin
    root = Path(workspace) / 'assets/full-examples'
    root.mkdir(parents=True, exist_ok=False)
    for name, values in (('a', [[1, 2], [3, 4]]), ('b', [[2, 4], [6, 8]]), ('binary', [[0, 1], [1, 0]])):
        with rasterio.open(root / (name + '.tif'), 'w', driver='GTiff', height=2, width=2, count=1, dtype='float32', crs='EPSG:4326', transform=from_origin(0, 2, 1, 1), nodata=-9999) as output:
            output.write(np.asarray(values, dtype='float32'), 1)
    points = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [x, y]}, 'properties': {'id': i, 'value': (i + 1) * 2}} for i, (x, y) in enumerate(((0.5, 0.5), (1.5, 1.5), (3, 3)))]}
    zones = {'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'zone_id': 'Z1'}, 'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}}]}
    for name, value in (('points.geojson', points), ('zones.geojson', zones)):
        (root / name).write_text(json.dumps(value), encoding='utf-8')
    (root / 'points.csv').write_text('lon,lat,value,zone\n0.5,0.5,2,A\n1.5,1.5,4,A\n', encoding='utf-8')
    records = [{'Country': 'Exampleland', 'Type': 'Flood', 'Disaster Type': 'Flood', 'Total Deaths': i, 'Start Year': 2020 + i, 'Start Month': 1, 'Start Day': 1, 'DisNo.': str(i)} for i in (1, 2)]
    pd.DataFrame(records).to_excel(root / 'events.xlsx', sheet_name='Events', index=False)
    pd.DataFrame(records).to_csv(root / 'events.csv', index=False)
    with (root / 'earthquakes.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['time', 'latitude', 'longitude', 'depth', 'mag', 'id', 'type', 'place'])
        writer.writeheader()
        for i, lat in enumerate((30, 31, 999)):
            writer.writerow({'time': f'2020-01-0{i + 1}T00:00:00Z', 'latitude': lat, 'longitude': 110, 'depth': 10, 'mag': 4 + i, 'id': str(i), 'type': 'earthquake', 'place': 'Synthetic'})
    (root / 'README.txt').write_text('Synthetic acceptance fixtures only. Not registered data, real events, or scientific ground truth.\n', encoding='utf-8')
    with rasterio.open(root / 'projected.tif', 'w', driver='GTiff', height=2, width=2,
                       count=1, dtype='float32', crs='EPSG:32650',
                       transform=from_origin(0, 2, 1, 1), nodata=-9999) as output:
        output.write(np.asarray([[1, 2], [3, 4]], dtype='float32'), 1)
    (root / 'kriging.csv').write_text(
        'x,y,value\n0.5,1.5,1\n1.5,1.5,2\n0.5,0.5,3\n1.5,0.5,4\n', encoding='utf-8')
    with rasterio.open(root / 'scientific-bands.tif', 'w', driver='GTiff',
                       height=2, width=2, count=2, dtype='float32', crs='EPSG:32650',
                       transform=from_origin(500000, 4400000, 10, 10), nodata=-9999) as output:
        output.write(np.asarray([[[1, 1], [1, 1]], [[3, 3], [3, 3]]], dtype='float32'))
    with rasterio.open(root / 'scientific-after.tif', 'w', driver='GTiff',
                       height=2, width=2, count=1, dtype='float32', crs='EPSG:32650',
                       transform=from_origin(0, 2, 1, 1), nodata=-9999) as output:
        output.write(np.asarray([[2, 1], [3, 4]], dtype='float32'), 1)
    from PIL import Image, ImageDraw
    picture = Image.new('RGB', (30, 20), 'white')
    drawing = ImageDraw.Draw(picture)
    drawing.rectangle((2, 2, 10, 10), fill=(200, 20, 20))
    drawing.rectangle((15, 2, 23, 10), fill=(20, 20, 200))
    picture.save(root / 'scientific-map.png')
    picture = Image.new('RGB', (50, 50), 'white')
    drawing = ImageDraw.Draw(picture)
    for column in range(5, 45):
        if column != 20:
            drawing.point((column, 49-column), fill=(0, 80, 180))
    picture.save(root / 'scientific-curve.png')
    return root

def close(actual, expected, rel=1e-06, absolute=1e-09):
    if not math.isclose(actual, expected, rel_tol=rel, abs_tol=absolute):
        raise AssertionError(f'Expected {expected}, obtained {actual}')

def oracle(name, response, workspace):
    value = response['result']
    if name in ('GeoRasterIndexAnalysis', 'GeoRasterChangeAnalysis', 'GeoMapColorExtract', 'GeoPlotDigitize'):
        assert response['artifacts'], 'Scientific file-producing tool returned no artifacts.'
        manifest_path = Path(workspace) / value['manifest_path']
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert manifest['schema'] == 'geoagent.scientific-image/v1'
        for item in value['outputs']:
            assert digest(Path(workspace) / item['path']) == item['sha256']
        stats = value['statistics']
        if name in ('GeoRasterIndexAnalysis', 'GeoRasterChangeAnalysis'):
            import numpy as np
            import rasterio
            with rasterio.open(manifest_path.parent / 'values.tif') as data:
                expected = [[.5, .5], [.5, .5]] if name == 'GeoRasterIndexAnalysis' else [[1, -1], [0, 0]]
                np.testing.assert_allclose(data.read(1), expected, rtol=0, atol=1e-7)
                assert data.crs.to_epsg() == 32650
            assert stats['valid_pixels'] == 4
            close(stats['mean'], .5 if name == 'GeoRasterIndexAnalysis' else 0)
        elif name == 'GeoMapColorExtract':
            assert stats['candidate_regions'] == 2 and stats['matched_pixels'] == 162
            vectors = json.loads((manifest_path.parent / 'regions.pixel.json').read_text())
            assert 'NOT RFC7946' in vectors['coordinate_space'] and len(vectors['features']) == 2
        else:
            assert stats['extracted_columns'] == 39 and stats['unmatched_columns'] == 1
            assert stats['interpolated_points'] == 0
            with (manifest_path.parent / 'curve.csv').open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            assert len(rows) == 39
            assert all(int(row['pixel_column']) != 20 for row in rows)
            assert all(float(row['x']) == float(row['y']) for row in rows)
    if name == 'GeoMagnitudeToEnergy':
        close(value['energy_j'], 10 ** 14.55, rel=0.0005)
        close(value['tnt_tons'], 10 ** 14.55 / 4184000000.0, rel=0.0005)
    if name.endswith('Bearing'):
        close(value['bearing_degrees'], 90)
    if name.endswith('DecimalToDMS'):
        assert value['axis'] == 'lat' and '30' in value['dms']
    if name.endswith('CheckCRSConsistency'):
        assert value['consistent'] is True
    if name.startswith(('CCS', 'DeepTime')) and name.endswith('HaversineDistance'):
        close(value['distance_km'], math.pi * 6371.0088 / 2)
    if name in ('CCSBBoxArea', 'DeepTimeBBoxArea', 'EnergyBBoxArea', 'OceanBBoxArea'):
        close(value['area_km2'], 6371.0088 ** 2 * math.pi / 180 * math.sin(math.pi / 180))
    expected = {'Mean': {'value': 2}, 'Difference': {'value': 5}, 'Division': {'value': 4}, 'PercentageChange': {'value': 50}, 'KelvinToCelsius': {'value': 26.85}, 'LinearTrend': {'slope': 2, 'intercept': 1}, 'MaxValueAndIndex': {'value': 3, 'index': 1}, 'MinValueAndIndex': {'value': 1, 'index': 0}, 'Argmax': {'index': 1}, 'SensSlope': {'slope': 2}, 'CoefficientOfVariation': {'value': math.sqrt(2 / 3) / 2}, 'Kurtosis': {'kurtosis': 1.64, 'excess_kurtosis': -1.36}}
    suffix = name.removeprefix('RemoteSensing')
    if suffix in expected:
        for key, number in expected[suffix].items():
            close(value[key], number)
    if name == 'ClimateCompareEpochs':
        assert value['differences_from_first'] == [0, 1, 2]
    for suffix, values in (('BatchImageMean', [2.5, 5]), ('BatchImageSum', [10, 20]), ('BatchHotspotPercentage', [50, 75])):
        if name == 'RemoteSensing' + suffix:
            assert [x['value'] for x in value['values']] == values
    if name == 'RemoteSensingListFiles':
        assert value['file_count'] == len(value['files'])
        assert any((Path(p).name == 'a.tif' for p in value['files']))
    if name in ('RemoteSensingNDVI', 'RemoteSensingNBR', 'RemoteSensingNDWI'):
        close(value['mean'], -1 / 3 if name.endswith('NDWI') else 1 / 3)
        assert value['finite_pixels'] == 4
    if name == 'RemoteSensingBatchNDSI':
        close(value['outputs'][0]['mean'], -1 / 3)
    if name in ('RemoteSensingTiffDifference', 'RemoteSensingSubtract'):
        close(value['mean'], 2.5)
    if name == 'RemoteSensingFireIncreaseMap':
        assert value['positive_pixels'] == 3
    if name == 'RemoteSensingCountAboveThreshold':
        assert value['count'] == 3 and value['percentage'] == 75
    if name == 'RemoteSensingExtremeSnowLossPercentage':
        assert value['count'] == 2 and value['percentage'] == 50
    if name.endswith(('StandardizeSpatialData', 'BatchVector')):
        assert not value['skipped_layers']
        assert value['standardized_layers'][0]['feature_count'] == 3
    if name.endswith('ValidateSpatialData'):
        assert value['validation_reports'][0]['valid'] == 3 and (not value['skipped_layers'])
    if name.endswith('NearestNeighbor'):
        assert len(value['nearest_neighbours']) == 3
        close(value['nearest_neighbours'][0]['distance_km'], 157.2406167863)
    if name.endswith('Buffer'):
        assert value['feature_count'] == 3 and value['buffer_distances_km'] == [1]
    if name.endswith('Overlay'):
        assert value['joined_count'] == 2 and value['tested_point_count'] == 3
    if name == 'GeoExactZonalStatistics':
        assert value['zone_count'] == 1
        row = value['zones'][0]
        for key, expected in {'coverage_count': 4, 'valid_area_m2': 4, 'mean': 2.5,
                              'coverage_weighted_sum': 10, 'minimum': 1, 'maximum': 4}.items():
            close(row[key], expected)
    elif name.endswith('ZonalStatistics'):
        assert value['zone_count'] == 1
        close(value['zone_statistics'][0]['value'], 3)
    if name == 'GeoOrdinaryKrigingGrid':
        assert value['sample_count'] == 4 and value['outside_hull_cells'] == 0
        close(value['prediction_min'], 1)
        close(value['prediction_max'], 4)
        close(value['variance_min'], 0)
        close(value['variance_max'], 0)
    if name == 'RemoteSensingMannKendallTest':
        assert value['n'] == 6 and value['trend'] == 'increasing'
        close(value['s'], 15)
        close(value['tau'], 1)
        close(value['variance_s'], 510 / 18)
        close(value['slope'], 1)
        assert value['slope_unit'] == 'ppm/year'
    if name.startswith('NaturalHazard'):
        if name.endswith('LoadEventTable'):
            assert value['record_count'] == 2 and value['sheet'] == 'Events'
        if name.endswith('FilterRecords'):
            assert value['record_count'] == 2
        if name.endswith('CountRecords'):
            assert value['count'] == 2
        if name.endswith('SumField'):
            assert value['sum'] == 3
        if name.endswith('SelectMaxRecord'):
            assert value['event']['Total Deaths'] == 2
        if name.endswith(('BuildStartDate', 'SelectLatest')):
            assert value['latest_date'] == '2022-01-01'
        if name.endswith('GroupAggregate'):
            assert value['ranking'] == [{'Type': 'Flood', 'count': 2}]
    if name == '地震数据清洗与分级':
        assert (value['input_rows'], value['clean_rows'], value['dropped_rows']) == (3, 2, 1)
    for artifact in response['artifacts']:
        path = Path(workspace) / artifact['path']
        assert path.is_file() and path.stat().st_size > 0 and (digest(path) == artifact['sha256'])
        if path.suffix.lower() in ('.tif', '.tiff'):
            import numpy as np
            import rasterio
            with rasterio.open(path) as raster:
                pixels = raster.read(1, masked=True).compressed()
                assert raster.crs is not None and pixels.size and np.isfinite(pixels).all()
                if name == 'RemoteSensingTiffAverage':
                    np.testing.assert_allclose(raster.read(1), [[1.5, 3], [4.5, 6]])
                if name in ('RemoteSensingTiffDifference', 'RemoteSensingSubtract'):
                    np.testing.assert_allclose(raster.read(1), [[1, 2], [3, 4]])
        if path.suffix.lower() == '.png':
            from PIL import Image
            with Image.open(path) as bitmap:
                bitmap.verify()
    if name.endswith(('RenderMap', 'Buffer', 'Overlay', 'StandardizeSpatialData', 'BatchVector', 'ValidateSpatialData', 'FilterRecords')) or name == '地震数据清洗与分级':
        assert response['artifacts'], 'File-producing tool returned no checked artifacts.'
