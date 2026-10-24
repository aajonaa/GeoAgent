"""Read physical raster observations using metadata, never filenames or task IDs."""
from __future__ import annotations
import math
import re
from .scientific_spatial import UnsupportedOperation
MOD09_RANGE_SOURCE = 'https://ladsweb.modaps.eosdis.nasa.gov/filespec/MODIS/5/MOD09GA.fs'

def read_scientific_raster(path):
    import numpy as np
    import rasterio
    with rasterio.open(path) as source:
        band_tags = {key.casefold(): value for key, value in source.tags(1).items()}
        dataset_tags = {key.casefold(): value for key, value in source.tags().items()}
        array = source.read(1, masked=True).astype('float64').filled(np.nan)
        scale, offset = (float(source.scales[0]), float(source.offsets[0]))
        scale_origin = 'GDAL band scale/offset'
        tagged_scale = band_tags.get('scale_factor', band_tags.get('scale'))
        tagged_offset = band_tags.get('add_offset', band_tags.get('offset'))
        if tagged_scale is not None:
            proposed = float(tagged_scale)
            if scale != 1 and (not math.isclose(scale, proposed, rel_tol=1e-12)):
                raise UnsupportedOperation('Conflicting raster scale metadata')
            scale, scale_origin = (proposed, 'explicit band scale tag')
        if tagged_offset is not None:
            proposed = float(tagged_offset)
            if offset != 0 and (not math.isclose(offset, proposed, rel_tol=1e-12)):
                raise UnsupportedOperation('Conflicting raster offset metadata')
            offset = proposed
        if not math.isfinite(scale) or not math.isfinite(offset) or scale == 0:
            raise UnsupportedOperation('Raster scale and offset must be finite, with nonzero scale')
        valid_range, range_origin = (None, 'nodata and finite observations only')
        if 'valid_range' in band_tags:
            values = re.findall('[-+]?\\d+(?:\\.\\d+)?(?:[eE][-+]?\\d+)?', band_tags['valid_range'])
            if len(values) != 2:
                raise UnsupportedOperation('Raster valid_range must declare exactly two raw-value bounds')
            valid_range, range_origin = (list(map(float, values)), 'explicit band valid_range')
        elif 'valid_min' in band_tags and 'valid_max' in band_tags:
            valid_range = [float(band_tags['valid_min']), float(band_tags['valid_max'])]
            range_origin = 'explicit band valid_min/valid_max'
        elif re.fullmatch('sur_refl_b0[1-7]', band_tags.get('name', '')) and ('MOD09GA' in dataset_tags.get('license', '').upper() or dataset_tags.get('shortname', '').upper() == 'MOD09GA'):
            valid_range, range_origin = ([-100.0, 16000.0], MOD09_RANGE_SOURCE)
        if valid_range is not None:
            low, high = valid_range
            if not math.isfinite(low) or not math.isfinite(high) or low > high:
                raise UnsupportedOperation('Invalid raster valid-range metadata')
            array[(array < low) | (array > high)] = np.nan
        array = array * scale + offset
        array[~np.isfinite(array)] = np.nan
        policy = {'source': str(path), 'nodata': source.nodata, 'scale': scale, 'offset': offset, 'scale_source': scale_origin, 'valid_raw_range_inclusive': valid_range, 'range_source': range_origin, 'quality_mask_applied': False}
        if isinstance(policy['nodata'], float) and (not math.isfinite(policy['nodata'])):
            policy['nodata'] = 'nonfinite nodata'
    return (array, policy)
