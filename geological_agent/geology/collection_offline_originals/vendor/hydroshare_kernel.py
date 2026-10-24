# Original HydroShare get_band_info. BSD-3-Clause in originals/100.
from osgeo import gdal
from osgeo.gdalconst import GA_ReadOnly
import numpy

def get_band_info(raster_file_name):

    raster_dataset = gdal.Open(raster_file_name, GA_ReadOnly)

    import os
    ori_dir = os.getcwd()
    os.chdir(os.path.dirname(raster_file_name))

    # get raster band count
    if raster_dataset:
        band_info = {}
        band_count = raster_dataset.RasterCount

        for i in range(0, band_count):
            band = raster_dataset.GetRasterBand(i + 1)
            stats = band.GetStatistics(False, True)
            if stats is not None:
                minimum, maximum, _, _ = stats
            else:
                continue
            no_data = band.GetNoDataValue()
            new_no_data = None

            if no_data and numpy.allclose(minimum, no_data):
                new_no_data = minimum
            elif no_data and numpy.allclose(maximum, no_data):
                new_no_data = maximum

            if new_no_data is not None:
                band.SetNoDataValue(new_no_data)
                minimum, maximum, _, _ = band.GetStatistics(False, False)

            band_info[i + 1] = {
                'name': 'Band_' + str(i + 1),
                'variableName': '',
                'variableUnit': band.GetUnitType(),
                'noDataValue': band.GetNoDataValue(),
                'maximumValue': maximum,
                'minimumValue': minimum,
            }
    else:
        band_info = {
            'name': 'Band_1',
            'variableName': '',
            'variableUnit': '',
            'noDataValue': None,
            'maximumValue': None,
            'minimumValue': None,
        }

    raster_dataset = None
    os.chdir(ori_dir)
    return band_info

if __name__ == "__main__":
    import sys, json
    print(json.dumps(get_band_info(sys.argv[1]), allow_nan=False))
