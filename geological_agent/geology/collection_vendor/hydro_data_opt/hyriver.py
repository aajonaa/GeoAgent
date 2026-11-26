# Integration scaffold around unchanged upstream source excerpts.
from __future__ import annotations
import pandas as pd
def exceedance(daily: pd.DataFrame | pd.Series, threshold: float = 1e-3) -> pd.DataFrame:
    """Compute exceedance probability from daily data.

    Parameters
    ----------
    daily : pandas.Series or pandas.DataFrame
        The data to be processed
    threshold : float, optional
        The threshold to compute exceedance probability, defaults to 1e-3.

    Returns
    -------
    pandas.Series or pandas.DataFrame
        Exceedance probability.
    """
    if isinstance(daily, pd.Series):
        daily = daily.to_frame()
    _daily = daily[daily > threshold].copy()
    ranks = _daily.rank(ascending=False, pct=True) * 100
    return pd.concat(
        (
            pd.DataFrame({c: _daily[c], f"{c}_rank": ranks[c]})
            .sort_values(by=f"{c}_rank")
            .reset_index(drop=True)
            for c in daily
        ),
        axis=1,
    )


