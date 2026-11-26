# Integration scaffold around unchanged upstream source excerpts.
import numpy as np
def sum_to_scale(
    values: np.ndarray,
    scale: int,
) -> np.ndarray:
    """
    Compute a sliding sums array using 1-D convolution. The initial
    (scale - 1) elements of the result array will be padded with np.nan values.
    Missing values are not ignored, i.e. if a np.nan
    (missing) value is part of the group of values to be summed then the sum
    will be np.nan

    A time-major spatial array with shape (time, ``*cells``) is summed window-wise along
    its time axis, so every cell's sliding sums are computed by one vectorized pass.

    For example if the first array is [3, 4, 6, 2, 1, 3, 5, 8, 5] and
    the number of values to sum is 3 then the resulting array
    will be [np.nan, np.nan, 13, 12, 9, 6, 9, 16, 18].

    More generally::

        Y = f(X, n)

        Y[i] = np.nan, where i < n - 1
        Y[i] = sum(X[i - n + 1 : i + 1]), where i >= n - 1 and X[i - n + 1 : i + 1] contains no NaN values
        Y[i] = np.nan, where i >= n - 1 and X[i - n + 1 : i + 1] contains one or more NaN values

    :param values: the array of values over which we'll compute sliding sums
    :param scale: the number of values for which each sliding summation will
        encompass, for example if this value is 3 then the first two elements of
        the output array will contain the pad value and the third element of the
        output array will contain the sum of the first three elements, and so on
    :return: an array of sliding sums, equal in length to the input values
        array, left padded with NaN values
    """

    # don't bother if the number of values to sum is 1
    if scale == 1:
        return values

    if np.ma.isMaskedArray(values):
        # a masked value stands for a missing value: make it an explicit NaN so the
        # convolution below and the window-wise spatial sum see the missing marker
        # rather than the data under the mask (np.convolve reads under it)
        values = np.ma.filled(values.astype(float), np.nan)

    if values.ndim > 2:
        # time-major spatial arrays are summed window-wise along the time axis: one
        # vectorized window per time step for every cell, no per-cell Python loop
        # (np.convolve is 1-D only). The NaN pad is float64, as the 1-D path's
        # np.hstack([np.nan, ...]) is, so single-precision input still accumulates in
        # double precision.
        pad_shape = (scale - 1, *values.shape[1:])
        padded = np.concatenate((np.full(pad_shape, np.nan, dtype=float), values))
        window_sums: np.ndarray = np.lib.stride_tricks.sliding_window_view(padded, scale, axis=0).sum(axis=-1)
        return window_sums

    # get the valid sliding summations with 1D convolution
    sliding_sums = np.convolve(values, np.ones(scale), mode="valid")

    # pad the first (n - 1) elements of the array with NaN values
    return np.hstack(([np.nan] * (scale - 1), sliding_sums))


