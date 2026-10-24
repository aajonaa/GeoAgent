# Original Pangaea geographic accessor methods. BSD-3-Clause in originals/124.
import numpy as np

class LSMGridKernel:

    def __init__(self, xarray_obj):
        self._obj = xarray_obj
        self._projection = None
        self._epsg = None
        self._geotransform = None
        self._affine = None
        self._center = None
        self._y_inverted = None

        # set variable information
        self.y_var = 'lat'
        self.x_var = 'lon'
        self.time_var = 'time'
        # set dimension information
        self.y_dim = 'y'
        self.x_dim = 'x'
        self.time_dim = 'time'
        # convert lon from [0 to 360] to [-180 to 180]
        self.lon_to_180 = False
        # coordinates are projected already
        self.coords_projected = False

    @property
    def y_inverted(self):
        """Is the y-coord inverted"""
        if self._y_inverted is None:
            y_coords = self._obj[self.y_var].values
            if y_coords.ndim == 3:
                y_coords = y_coords[0]
            if y_coords.ndim == 2:
                self._y_inverted = (y_coords[-1, 0] > y_coords[0, 0])
            else:
                self._y_inverted = (y_coords[-1] > y_coords[0])
        return self._y_inverted

    @property
    def _raw_coords(self):
        """Gets the raw coordinated of dataset"""
        x_coords = self._obj[self.x_var].values
        y_coords = self._obj[self.y_var].values

        if x_coords.ndim == 3:
            x_coords = x_coords[0]
        if y_coords.ndim == 3:
            y_coords = y_coords[0]

        if x_coords.ndim < 2:
            x_coords, y_coords = np.meshgrid(x_coords, y_coords)

        # WRF & NWM Grids are upside down
        if self.y_inverted:
            x_coords = x_coords[::-1]
            y_coords = y_coords[::-1]

        return y_coords, x_coords

    @property
    def latlon(self):
        """Returns lat,lon arrays

            .. warning:: The grids always be returned with [0,0]
                as Northeast and [-1,-1] as Southwest.
        """
        if 'MAP_PROJ' in self._obj.attrs:
            lat, lon = wrf.latlon_coords(self._obj, as_np=True)
            if lat.ndim == 3:
                lat = lat[0]
            if lon.ndim == 3:
                lon = lon[0]
            # WRF Grid is upside down
            lat = lat[::-1]
            lon = lon[::-1]
        else:
            lat, lon = self._raw_coords

        if self.coords_projected:
            lon, lat = transform(Proj(self.projection.ExportToProj4()),
                                 Proj(init='epsg:4326'),
                                 lon,
                                 lat)

        if self.lon_to_180:
            lon = (lon + 180) % 360 - 180  # convert [0, 360] to [-180, 180]

        return lat, lon

    @property
    def center(self):
        """Return the geographic center point of this dataset."""
        if self._center is None:
            # we can use a cache on our accessor objects, because accessors
            # themselves are cached on instances that access them.
            lat, lon = self.latlon
            self._center = (float(np.nanmean(lon)), float(np.nanmean(lat)))
        return self._center

    def _getvar(self, variable, yslice, xslice):
        """Get the variable either directly or calculated"""
        # FAILED ATTEMPT TO USE wrf.getvar
        # if 'MAP_PROJ' in self._obj.attrs:
        #    try:
        #        nc_file = self._obj._file_obj.ds
        #    except AttributeError:
        #        nc_file = self._obj._file_obj.file_objs
        #    var = wrf.getvar(nc_file, variable)
        def extract_slice(var, slice_arr):
            """extract by slice"""
            if var.ndim == 4:
                var = var[slice_arr[0], slice_arr[1],
                          slice_arr[2], slice_arr[3]]
            if var.ndim == 3:
                var = var[slice_arr[0], slice_arr[1], slice_arr[2]]
            else:
                var = var[slice_arr[0], slice_arr[1]]
            return var

        var = self._obj[variable]
        slc = [slice(None)] * var.ndim
        # flip in y-direction
        if self.y_inverted:
            slc[var.get_axis_num(self.y_dim)] = slice(None, None, -1)
            var = extract_slice(var, slc)
        # get data out
        slc[var.get_axis_num(self.x_dim)] = xslice
        slc[var.get_axis_num(self.y_dim)] = yslice
        return extract_slice(var, slc)
