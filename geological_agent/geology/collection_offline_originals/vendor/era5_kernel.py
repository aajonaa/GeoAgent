# Original ERA5-tools monthly notebook statements. GPL-3.0 in originals/31.
def monthly_climate(xarray_src, param, lon, lat):

    ds_by_month = xarray_src.groupby('time.month').mean('time')

    time_serie = xarray_src[param].sel(longitude=lon, latitude=lat, method="nearest", tolerance=0.051)# tolerance of 1/2 latitude and longitude step (0.1 degree) 

    return ds_by_month, time_serie
