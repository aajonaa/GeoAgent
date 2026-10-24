# Integration scaffold around unchanged upstream source excerpts.
from __future__ import annotations
from typing import Callable
import numpy as np
import pandas as pd
import xarray as xr
from .camels_conventions import *
def column_values(df: pd.DataFrame, colname: str) -> np.ndarray:
    return df[[colname]].values.transpose().squeeze()


timestamp_v = np.vectorize(pd.Timestamp)


def negative_is_missing(x: np.ndarray) -> np.ndarray:
    return x < 0.0


def load_csv_stations_tseries(
    filename: str,
    is_missing: Callable[[np.ndarray], np.ndarray] = None,
    units: str = None,
    dtype=None,
) -> xr.DataArray:
    """Loads a CAMELS-Aus time series from a comma-separated values file

    Args:
        filename (str): filename
        is_missing (Callable[[np.ndarray], np.ndarray], optional): Function that post-processes the loaded time series to set missing values to np.nan (e.g. replace all negative values). Defaults to None, in which case nothing is changed.
        units (str, optional): Units of the time series. Defaults to None.
        dtype ([type], optional): expected column type. See pandas.read_csv. Defaults to None.

    Returns:
        xr.DataArray: A multivariate time series, xarray of dimension 2 (time X stations)
    """
    if dtype is None:
        dtype = "str"
    c_flows = pd.read_csv(filename, index_col=False, dtype=dtype)
    # TODO sanity checks
    indx = timestamp_v(
        year=column_values(c_flows, "year").astype(np.int32),
        month=column_values(c_flows, "month").astype(np.int32),
        day=column_values(c_flows, "day").astype(np.int32),
    )
    x = c_flows.drop(["year", "month", "day"], axis=1)
    x.index = pd.DatetimeIndex(indx)
    if not is_missing is None:
        missing = is_missing(x)
        x[missing] = np.nan
    res = xr.DataArray(
        x.values,
        coords={TIME_DIM_NAME: pd.DatetimeIndex(indx), STATION_ID_VARNAME: x.columns},
        dims=[TIME_DIM_NAME, STATION_ID_VARNAME],
    )
    set_xr_units(res, units)
    return res


