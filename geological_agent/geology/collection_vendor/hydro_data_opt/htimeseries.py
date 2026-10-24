# Integration scaffold around unchanged upstream source excerpts.
import csv
import numpy as np
import pandas as pd
def _check_timeseries_index_has_no_duplicates(data, error_message_prefix):
    duplicate_dates = data.index[data.index.duplicated()].tolist()
    if duplicate_dates:
        dates_str = ", ".join([str(x) for x in duplicate_dates])
        raise ValueError(
            f"{error_message_prefix}: the following timestamps appear more than "
            f"once: {dates_str}"
        )


class TimeseriesRecordsReader:
    def __init__(self, f, start_date, end_date, tzinfo):
        self.f = f
        self.start_date = start_date
        self.end_date = end_date
        self.tzinfo = tzinfo


    def _read_data_from_stream(self, f):
        dates, values, flags = self._read_csv(f)
        dates = self._localize_dates(dates)
        result = pd.DataFrame(
            {
                "value": np.array(values, dtype=np.float64),
                "flags": np.array(flags, dtype=str),
            },
            index=dates,
        )
        result.index.name = "date"
        return result


    def _localize_dates(self, dates):
        try:
            result = pd.to_datetime(dates)
        except ValueError:
            raise ValueError(
                "Could not parse timestamps correctly. Maybe the CSV contains mixed "
                "aware and naive timestamps."
            )
        if len(result) == 0 or (len(result) > 0 and result[0].tzinfo is None):
            result = pd.to_datetime(dates).tz_localize(
                self.tzinfo, ambiguous=len(dates) * [True]
            )
        return result


    def _read_csv(self, f):
        dates, values, flags = [], [], []
        for row in csv.reader(f):  # We don't use pd.read_csv() because it's much slower
            if not len(row):
                continue
            dates.append(row[0])
            if len(row) > 1 and row[1]:
                values.append(row[1])
            else:
                values.append("NaN")
            flags.append(row[2] if len(row) > 2 else "")
        return dates, values, flags


    def _check_there_are_no_duplicates(self, data):
        _check_timeseries_index_has_no_duplicates(
            data, error_message_prefix="Can't read time series"
        )


