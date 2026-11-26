# Integration scaffold around unchanged upstream source excerpts.
from typing import Any
import pandas as pd
def daily_average(
    df: pd.DataFrame,
    rolling: bool = False,
    **kwargs: Any,  # noqa: ANN401
) -> pd.DataFrame:
    """Calculate daily seasonal averages of the timeseries data in a DataFrame.

    Parameters
    ----------
    df: DataFrame
        A pandas DataFrame with a datetime index and columns containing float type values.

    rolling: bool
        If True, will calculate the rolling seasonal average.

    ``**kwargs``: pandas.DataFrame.rolling() properties, optional
        Options for how to compute the rolling averages. If not provided, the default is to use the
        following parameters: {window=6, min_periods=1, center=True, closed="right"}. Specifying
        ``**kwargs`` will clear the defaults.

    Returns
    -------
    DataFrame
        A pandas dataframe with a string type index of date representations and the daily seasonal
        averages as float values in the columns.

    Examples
    --------
    >>> import hydrostats.data as hd
    >>> import pandas as pd
    >>> pd.options.display.max_rows = 15

    The data URLs contain streamflow data from two different models, and are provided from the
    Hydrostats Github page

    >>> sfpt_url = r"https://github.com/waderoberts123/Hydrostats/raw/master/Sample_data/sfpt_data/magdalena-calamar_interim_data.csv"
    >>> glofas_url = r"https://github.com/waderoberts123/Hydrostats/raw/master/Sample_data/GLOFAS_Data/magdalena-calamar_ECMWF_data.csv"
    >>> merged_df = hd.merge_data(
    ...     sfpt_url, glofas_url, column_names=("Streamflow Prediction Tool", "GLOFAS")
    ... )

    >>> hd.daily_average(merged_df)
           Streamflow Prediction Tool       GLOFAS
    01/01                 7331.305278  7676.792460
    01/02                 7108.640746  7753.671798
    01/03                 6927.147740  7631.900453
    01/04                 6738.162886  7483.029897
    01/05                 6552.914171  7316.004227
    01/06                 6388.213829  7154.650963
    01/07                 6258.418600  7012.279722
                               ...          ...
    12/25                 8321.367143  8948.101821
    12/26                 8149.313143  8903.544978
    12/27                 7994.357429  8807.690639
    12/28                 7872.819143  8642.877365
    12/29                 7791.741143  8435.175677
    12/30                 7729.451143  8225.315074
    12/31                 7656.042286  8041.918136
    [366 rows x 2 columns]
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex")

    # Calculating the daily average from the database
    if not rolling:
        daily_averages = df.groupby(df.index.strftime("%m/%d")).mean()
    elif kwargs:
        rolling_averages = df.rolling(**kwargs).mean()
        daily_averages = daily_average(rolling_averages, rolling=False)
    else:
        rolling_averages = df.rolling(window=6, min_periods=1, center=True, closed="right").mean()
        daily_averages = daily_average(rolling_averages, rolling=False)

    return daily_averages


