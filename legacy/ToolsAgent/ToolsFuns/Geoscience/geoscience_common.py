import math
from ..source_contracts import arguments as source_arguments, result as source_result

def geo_check_crs_consistency(input_str):
    """Structured source API; JSON-object strings are transport compatibility only."""
    params = source_arguments('GeoCheckCRSConsistency', input_str)
    identifiers = [item.strip().upper() for item in params['crs_values']]
    value = {'consistent': len(set(identifiers)) == 1, 'values': identifiers}
    return source_result('GeoCheckCRSConsistency', value)

def geo_haversine_distance(input_str):
    """Structured source API; JSON-object strings are transport compatibility only."""
    params = source_arguments('GeoHaversineDistance', input_str)
    p1, p2 = (math.radians(params['lat1']), math.radians(params['lat2']))
    dp = p2 - p1
    dl = math.radians(params['lon2'] - params['lon1'])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    value = {'distance_km': 2 * 6371.0088 * math.asin(math.sqrt(min(1.0, max(0.0, a))))}
    return source_result('GeoHaversineDistance', value)

def geo_magnitude_to_energy(input_str):
    """Structured source API; JSON-object strings are transport compatibility only."""
    params = source_arguments('GeoMagnitudeToEnergy', input_str)
    energy = 10.0 ** (1.5 * params['mw'] + 4.8)
    if not math.isfinite(energy) or energy <= 0:
        raise ValueError('Magnitude produces unrepresentable energy.')
    value = {'energy_j': energy, 'tnt_tons': energy / 4184000000.0}
    return source_result('GeoMagnitudeToEnergy', value)

def geo_bearing(input_str):
    """Structured source API; JSON-object strings are transport compatibility only."""
    params = source_arguments('GeoBearing', input_str)
    p1, p2 = (math.radians(params['lat1']), math.radians(params['lat2']))
    dl = math.radians(params['lon2'] - params['lon1'])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    value = {'bearing_degrees': (math.degrees(math.atan2(y, x)) + 360) % 360}
    return source_result('GeoBearing', value)

def geo_decimal_to_dms(input_str):
    """Structured source API; JSON-object strings are transport compatibility only."""
    params = source_arguments('GeoDecimalToDMS', input_str)
    axis, coordinate = (params['axis'], params['value'])
    total_hundredths = round(abs(coordinate) * 3600 * 100)
    degrees, remaining = divmod(total_hundredths, 360000)
    minutes, hundredths = divmod(remaining, 6000)
    seconds = hundredths / 100
    direction = ('N' if coordinate >= 0 else 'S') if axis == 'lat' else 'E' if coordinate >= 0 else 'W'
    dms = f"""{degrees}°{minutes}'{seconds:.2f}" {direction}"""
    value = {'axis': axis, 'decimal_degrees': coordinate, 'dms': dms}
    return source_result('GeoDecimalToDMS', value)

def geo_wgs84_bbox_area_km2(input_str):
    """Structured source API; JSON-object strings are transport compatibility only."""
    params = source_arguments('GeoWGS84BBoxAreaKm2', input_str)
    west, south, east, north = (params[k] for k in ('min_lon', 'min_lat', 'max_lon', 'max_lat'))
    value = {'area_km2': 6371.0088 ** 2 * math.radians(east - west) * (math.sin(math.radians(north)) - math.sin(math.radians(south)))}
    return source_result('GeoWGS84BBoxAreaKm2', value)
