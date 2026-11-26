# Original GeoNotebook methods. Apache-2.0 license in originals/10.
import numpy as np
from rasterio.crs import CRS
from rasterio.features import rasterize
from rasterio.warp import transform
from shapely.geometry import Polygon as sPolygon

def transform_coordinates(source_srs, target_srs, x, y):
    return tuple(i[0] for i in transform(source_srs, target_srs, x, y))

class AnnotationWindowKernel:
    def get_data_window(self, minx, miny, maxx, maxy):
        return ((
            int(min(minx, maxx)),
            int(min(miny, maxy))
        ), (
            int(max(minx, maxx)),
            int(max(miny, maxy)))
        )

class PolygonSubsetKernel:
    def subset(self, raster_data, **kwargs):
        # It is possible our user has drawn a polygon where part of the
        # shape is outside the dataset,  intersect with the rasterdata
        # shape to make sure we don't try to select/mask data that is
        # outside the bounds of our dataset.

        # Convert the image corner coordinates to WGS84
        trgt_srs = CRS.from_string("EPSG:4326")
        src_srs = raster_data.crs
        transformed = [transform_coordinates(src_srs, trgt_srs, [i[0]], [i[1]])
                       for i in raster_data.shape.exterior.coords]
        reprojected_data_extent = sPolygon(transformed)
        clipped = self.intersection(reprojected_data_extent)

        # Polygon is completely outside the dataset, return whatever
        # would have been returned by get_data()
        if not bool(clipped):
            ul = raster_data.index(self.bounds[0], self.bounds[1])
            lr = raster_data.index(self.bounds[2], self.bounds[3])
            window = self.get_data_window(ul[0], ul[1], lr[0], lr[1])

            return raster_data.get_data(window=window, **kwargs)

        ul = raster_data.index(clipped.bounds[0], clipped.bounds[1])
        lr = raster_data.index(clipped.bounds[2], clipped.bounds[3])
        window = self.get_data_window(ul[0], ul[1], lr[0], lr[1])

        data = raster_data.get_data(window=window, **kwargs)

        # out_shape must be determined from data's shape,  get_data
        # may have returned a bounding box of data that is smaller than
        # the implicit shape of the window we passed.  e.g. if the window
        # is partially outside the extent of the raster data. Note that
        # we index with negative numbers here because we may or may not
        # have a time dimension.
        num_bands = len(raster_data.band_indexes)

        if num_bands > 1:
            out_shape = data.shape[-3], data.shape[-2]
        else:
            out_shape = data.shape[-2], data.shape[-1]

        coordinates = []
        for lat, lon in clipped.exterior.coords:
            x, y = raster_data.index(lat, lon)
            coordinates.append((y - window[0][1], x - window[0][0]))

        # Mask the final polygon
        mask = rasterize(
            [({'type': 'Polygon',
               'coordinates': [coordinates]}, 0)],
            out_shape=out_shape, fill=1, all_touched=True, dtype=np.uint8)

        # If we have more than one band,  expand the mask so it includes
        # A "channel" dimension (e.g.  shape is now (lat, lon, channel))
        if num_bands > 1:
            mask = mask[..., np.newaxis] * np.ones(num_bands)

        # Finally broadcast mask to data because data may be from a
        # Raster data collection and include a time component
        # (e.g.  shape could be (time, lat, lon),  or even
        #  (time, lat, lon, channels))
        _, mask = np.broadcast_arrays(data, mask)
        data[mask.astype(bool)] = raster_data.nodata

        return np.ma.masked_equal(data, raster_data.nodata)
