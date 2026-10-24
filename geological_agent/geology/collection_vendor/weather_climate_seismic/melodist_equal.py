# Adaptation: isolated upstream function bodies with import/class glue added.
# Copyright (C) 2016-2023 Florian Hanzer, Kristian Förster, Benjamin Winter, Thomas Marke
# Original algorithms unchanged; full upstream license in licenses/.
import pandas as pd

def hourly_index(daily_index, fill_gaps=False):
    index = pd.date_range(start=daily_index.min(), end=daily_index.max().replace(hour=23), freq='h')

    # remove days that are not in the daily index:
    if not fill_gaps and len(index) > len(daily_index) * 24:
        df = pd.DataFrame(index=index.date, data=dict(hour=index.hour, keep=True))
        df.index = df.index.to_datetime()
        dropdates = list(set(index.date) - set(daily_index.date))
        df.loc[dropdates, 'keep'] = False
        df = df[df.keep]
        index = pd.DatetimeIndex(
            [
                pd.datetime(y, m, d, h)
                for y, m, d, h in zip(df.index.year, df.index.month, df.index.day, df.hour)
            ]
        )

    return index


def distribute_equally(daily_data, divide=False):
    """Obtains hourly values by equally distributing the daily values.

    Args:
        daily_data: daily values
        divide: if True, divide resulting values by the number of hours in
            order to preserve the daily sum (required e.g. for precipitation).

    Returns:
        Equally distributed hourly values.
    """

    index = hourly_index(daily_data.index)
    hourly_data = daily_data.reindex(index)
    hourly_data = hourly_data.groupby(hourly_data.index.day).transform(
        lambda x: x.ffill(limit=23)
    )

    if divide:
        hourly_data /= 24

    return hourly_data


