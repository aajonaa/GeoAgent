# Adaptation: isolated upstream function bodies with import/class glue added.
# Pangeo-data scikit-downscale contributors; Apache-2.0
# Original algorithms unchanged; full upstream license in licenses/.
from __future__ import annotations
import collections
from typing import Any, Literal
import numpy as np
from numpy.typing import NDArray
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.linear_model import LinearRegression
from sklearn.utils import check_array
from sklearn.utils.validation import check_is_fitted, validate_data

SYNTHETIC_MIN = -1e20


SYNTHETIC_MAX = 1e20


Cdf = collections.namedtuple('CDF', ['pp', 'vals'])


def plotting_positions(n: int, alpha: float = 0.4, beta: float = 0.4) -> NDArray[np.floating[Any]]:
    """Returns a monotonic array of plotting positions.

    Parameters
    ----------
    n : int
        Length of plotting positions to return.
    alpha, beta : float
        Plotting positions parameter. Default is 0.4.

    Returns
    -------
    positions : ndarray
        Quantile mapped data with shape from `input_data` and probability
        distribution from `data_to_match`.

    See Also
    --------
    scipy.stats.mstats.plotting_positions
    """
    return (np.arange(1, n + 1) - alpha) / (n + 1.0 - alpha - beta)


class QuantileMappingReressor(RegressorMixin, BaseEstimator):
    """Transform features using quantile mapping.

    Parameters
    ----------
    extrapolate : str, optional
        How to extend the cdfs at the tails. Valid options include {`'min'`, `'max'`, `'both'`, `'1to1'`, `None`}
    n_endpoints : int
        Number of endpoints to include when extrapolating the tails of the cdf

    Attributes
    ----------
    _X_cdf : Cdf
        NamedTuple representing the fit's X cdf
    _y_cdf : Cdf
        NamedTuple representing the fit's y cdf
    """

    _fit_attributes = ['_X_cdf', '_y_cdf']

    def __init__(
        self,
        extrapolate: Literal['min', 'max', 'both', '1to1'] | None = None,
        n_endpoints: int = 10,
    ) -> None:
        self.extrapolate = extrapolate
        self.n_endpoints = n_endpoints

        if self.n_endpoints < 2:
            raise ValueError('Invalid number of n_endpoints, must be >= 2')

    def _validate_data(self, X, y=None, reset=True, **check_params):
        """Validate input data using sklearn's validate_data."""
        return validate_data(self, X=X, y=y, reset=reset, **check_params)

    def fit(self, X, y, **kwargs):
        """Fit the quantile mapping regression model.

        Parameters
        ----------
        X : array-like, shape  [n_samples, 1]
            Training data.

        Returns
        -------
        self : object
        """
        X = check_array(
            X, dtype='numeric', ensure_min_samples=2 * self.n_endpoints + 1, ensure_2d=True
        )
        y = check_array(
            y, dtype='numeric', ensure_min_samples=2 * self.n_endpoints + 1, ensure_2d=False
        )

        X = check_max_features(X, n=1)

        self._X_cdf = self._calc_extrapolated_cdf(X, sort=True, extrapolate=self.extrapolate)
        self._y_cdf = self._calc_extrapolated_cdf(y, sort=True, extrapolate=self.extrapolate)

        return self

    def predict(self, X, **kwargs):
        """Predict regression for target X.

        Parameters
        ----------
        X : array_like, shape [n_samples, 1]
            Samples.

        Returns
        -------
        y : ndarray of shape (n_samples, )
            Predicted data.
        """
        check_is_fitted(self, self._fit_attributes)
        X = check_array(X, ensure_2d=True)

        X = X[:, 0]

        sort_inds = np.argsort(X)

        X_cdf = self._calc_extrapolated_cdf(X[sort_inds], sort=False, extrapolate=self.extrapolate)

        # Fill value for when x < xp[0] or x > xp[-1] (i.e. when X_cdf vals are out of range for self._X_cdf vals)
        left = -np.inf if self.extrapolate in ['min', 'both'] else None
        right = np.inf if self.extrapolate in ['max', 'both'] else None
        # For all values in future X, find the corresponding percentile in historical X
        X_cdf.pp[:] = np.interp(
            X_cdf.vals, self._X_cdf.vals, self._X_cdf.pp, left=left, right=right
        )

        # Extrapolate the tails beyond 1.0 to handle "new extremes", only triggered when the new extremes are even more drastic then
        # the linear extrapolation result from historical X at SYNTHETIC_MIN and SYNTHETIC_MAX
        if np.isinf(X_cdf.pp).any():
            lower_inds = np.nonzero(-np.inf == X_cdf.pp)[0]
            upper_inds = np.nonzero(np.inf == X_cdf.pp)[0]
            model = LinearRegression()
            if len(lower_inds):
                s = slice(lower_inds[-1] + 1, lower_inds[-1] + 1 + self.n_endpoints)
                model.fit(X_cdf.pp[s].reshape(-1, 1), X_cdf.vals[s].reshape(-1, 1))
                X_cdf.pp[lower_inds] = model.predict(X_cdf.vals[lower_inds].reshape(-1, 1))
            if len(upper_inds):
                s = slice(upper_inds[0] - self.n_endpoints, upper_inds[0])
                model.fit(X_cdf.pp[s].reshape(-1, 1), X_cdf.vals[s].reshape(-1, 1))
                X_cdf.pp[upper_inds] = model.predict(X_cdf.vals[upper_inds].reshape(-1, 1))

        # do the full quantile mapping
        y_hat = np.full_like(X, np.nan)
        y_hat[sort_inds] = np.interp(X_cdf.pp, self._y_cdf.pp, self._y_cdf.vals)[1:-1]

        # If extrapolate is 1to1, apply the offset between X and y to the
        # tails of y_hat
        if self.extrapolate == '1to1':
            y_hat = self._extrapolate_1to1(X, y_hat)

        return y_hat

    def _extrapolate_1to1(self, X, y_hat):
        X_fit_len = len(self._X_cdf.vals)
        X_fit_min = self._X_cdf.vals[0]
        X_fit_max = self._X_cdf.vals[-1]

        y_fit_len = len(self._y_cdf.vals)
        y_fit_min = self._y_cdf.vals[0]
        y_fit_max = self._y_cdf.vals[-1]

        # adjust values over fit max
        inds = X > X_fit_max
        if inds.any():
            if X_fit_len == y_fit_len:
                y_hat[inds] = y_fit_max + (X[inds] - X_fit_max)
            elif X_fit_len > y_fit_len:
                X_fit_at_y_fit_max = np.interp(self._y_cdf.pp[-1], self._X_cdf.pp, self._X_cdf.vals)
                y_hat[inds] = y_fit_max + (X[inds] - X_fit_at_y_fit_max)
            elif X_fit_len < y_fit_len:
                y_fit_at_X_fit_max = np.interp(self._X_cdf.pp[-1], self._y_cdf.pp, self._y_cdf.vals)
                y_hat[inds] = y_fit_at_X_fit_max + (X[inds] - X_fit_max)

        # adjust values under fit min
        inds = X < X_fit_min
        if inds.any():
            if X_fit_len == y_fit_len:
                y_hat[inds] = y_fit_min + (X[inds] - X_fit_min)
            elif X_fit_len > y_fit_len:
                X_fit_at_y_fit_min = np.interp(self._y_cdf.pp[0], self._X_cdf.pp, self._X_cdf.vals)
                y_hat[inds] = X_fit_min + (X[inds] - X_fit_at_y_fit_min)
            elif X_fit_len < y_fit_len:
                y_fit_at_X_fit_min = np.interp(self._X_cdf.pp[0], self._y_cdf.pp, self._y_cdf.vals)
                y_hat[inds] = y_fit_at_X_fit_min + (X[inds] - X_fit_min)

        return y_hat

    def _calc_extrapolated_cdf(
        self, data, sort=True, extrapolate=None, pp_min=SYNTHETIC_MIN, pp_max=SYNTHETIC_MAX
    ):
        """Calculate a new extrapolated cdf

        The goal of this function is to create a CDF with bounds outside the [0, 1] range.
        This allows for quantile mapping beyond observed data points.

        Parameters
        ----------
        data : array_like, shape [n_samples, 1]
            Input data (can be unsorted)
        sort : bool
            If true, sort the data before building the CDF
        extrapolate : str or None
            How to extend the cdfs at the tails. Valid options include {`'min'`, `'max'`, `'both'`, `'1to1'`, `None`}
        pp_min, pp_max : float
            Plotting position min/max values.

        Returns
        -------
        cdf : Cdf (NamedTuple)
        """

        n = len(data)

        # plotting positions
        pp = np.empty(n + 2)
        pp[1:-1] = plotting_positions(n)

        # extended data values (sorted)
        if data.ndim == 2:
            data = data[:, 0]
        if sort:
            data = np.sort(data)
        vals = np.full(n + 2, np.nan)
        vals[1:-1] = data
        vals[0] = data[0]
        vals[-1] = data[-1]

        # Add endpoints to the vector of plotting positions
        if extrapolate in [None, '1to1']:
            pp[0] = pp[1]
            pp[-1] = pp[-2]
        elif extrapolate == 'both':
            pp[0] = pp_min
            pp[-1] = pp_max
        elif extrapolate == 'max':
            pp[0] = pp[1]
            pp[-1] = pp_max
        elif extrapolate == 'min':
            pp[0] = pp_min
            pp[-1] = pp[-2]
        else:
            raise ValueError(f'unknown value for extrapolate: {extrapolate}')

        if extrapolate in ['min', 'max', 'both']:
            model = LinearRegression()

            # extrapolate lower end point
            if extrapolate in ['min', 'both']:
                s = slice(1, self.n_endpoints + 1)
                # fit linear model to first n_endpoints
                model.fit(pp[s].reshape(-1, 1), vals[s].reshape(-1, 1))
                # calculate the data value pp[0]
                vals[0] = model.predict(pp[0].reshape(-1, 1))

            # extrapolate upper end point
            if extrapolate in ['max', 'both']:
                s = slice(-self.n_endpoints - 1, -1)
                # fit linear model to last n_endpoints
                model.fit(pp[s].reshape(-1, 1), vals[s].reshape(-1, 1))
                # calculate the data value pp[-1]
                vals[-1] = model.predict(pp[-1].reshape(-1, 1))

        return Cdf(pp, vals)

    def __sklearn_tags__(self):
        from dataclasses import replace

        tags = super().__sklearn_tags__()
        # Skip tests - only supports 1 feature
        tags = replace(tags, _skip_test='QuantileMappingReressor only supports 1 feature')
        return tags


def check_max_features(array: ArrayLike, n: int = 1) -> ArrayLike:
    if array.ndim == 1:
        pass
    elif array.ndim == 2:
        n_features = array.shape[1]
        if n_features > n:
            raise ValueError(
                f'Found array with {n_features} features (shape={array.shape}) while '
                f'a maximum of {n} is required'
            )

    else:
        raise ValueError(
            f'Found array with {array.ndim} dimensions. Unclear which should be the feature dim.'
        )
    return array


