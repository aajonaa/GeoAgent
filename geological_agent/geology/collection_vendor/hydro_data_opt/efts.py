# Integration scaffold around unchanged upstream source excerpts.
from __future__ import annotations
import numpy as np
import xarray as xr
from .efts_conventions import *
def _first_where(condition):
    x = np.where(condition)[0]
    if len(x) < 1:
        raise Exception("first_where: Invalid condition, no element is true")
    return x[0]


class EftsDataSet:
    def get_ensemble_forecasts(self, variable_name = "rain_sim", identifier:str = None, dimension_id = None, start_time = None, lead_time_count = None) -> xr.DataArray:
        # Return a time series, ensemble of forecasts over the lead time
        if dimension_id is None: 
            dimension_id = self.get_stations_varname()
        td = self.get_time_dim()
        if start_time is None:
            start_time = td[0]
        nEns = self.get_ensemble_size()
        index_id = self.index_for_identifier(identifier, dimension_id)
        check_index_found(index_id, identifier, dimension_id)
        if lead_time_count is None:
            lead_time_count = self.get_lead_time_count()
        indTime = self.index_for_time(start_time)
        # float rain_sim[lead_time,station,ens_member,time]
        ensData = self.data.get(variable_name)[indTime,:nEns,index_id,:lead_time_count]
        # ensData = self.data.get(variable_name), start = [1, index_id, 1, indTime], 
        #     count = c(lead_time_count, 1, nEns, 1), collapse_degen = FALSE)
        # tu = self.get_lead_time_unit()
        # if tu == "days":
        #     timeAxis = start_time + pd.Timedelta(ncfile$dim$lead_time$vals)
        # } else {
        # timeAxis = start_time + lubridate::dhours(1) * ncfile$dim$lead_time$vals
        # }
        # out = xts(x = ensData[, 1, , 1], order.by = timeAxis, tzone = tz(start_time))
        return ensData


    def get_ensemble_size(self):
        # Length of the ensemble size dimension
        return self.data.dims[self.ensemble_member_dim_name]


    def get_lead_time_count(self):
        # Length of the lead time dimension
        return self.data.dims[self.lead_time_dim_name]


    def get_time_dim(self):
        # Gets the time dimension variable as a vector of date-time stamps
        return self.data.time.values # but loosing attributes.


    def _get_values(self, variable_name):
        # Gets (and cache in memory) all the values in a variable. Should be used only for dimension variables
        if not variable_name in conventional_varnames:
            raise Exception(variable_name+ " cannot be directly retrieved. Must be in " + ", ".join(conventional_varnames))
        return self.data[variable_name].values


    def index_for_identifier(self, identifier, dimension_id = None):
        # Gets the index at which an identifier is found in a dimension variable
        if dimension_id is None: dimension_id = self.get_stations_varname()
        identValues = self._get_values(dimension_id)
        if identifier is None:
            raise Exception("Identifier cannot be NA")
        else:
            return _first_where(identifier == identValues)


    def index_for_time(self, dateTime):
        # Gets the index at which a date-time is found in the main time axis of this data set
        return _first_where(self.data.time == dateTime)


