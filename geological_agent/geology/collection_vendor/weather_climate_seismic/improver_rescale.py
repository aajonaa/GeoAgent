# Adaptation: isolated upstream function bodies with import/class glue added.
# (C) Crown Copyright, Met Office. All rights reserved.
# Original algorithms unchanged; full upstream license in licenses/.
from typing import List, Optional, Tuple, Union
import numpy as np
from numpy import ndarray

def rescale(
    data: ndarray,
    data_range: Optional[Union[Tuple[float, float], List[float]]] = None,
    scale_range: Union[Tuple[float, float], List[float]] = (0.0, 1.0),
    clip: bool = False,
) -> ndarray:
    """
    Rescale data array so that data_min => scale_min
    and data_max => scale max.
    All adjustments are linear

    Args:
        data:
            Source values
        data_range:
            List containing two floats
            Lowest and highest source value to rescale.
            Default value of None is converted to [min(data), max(data)]
        scale_range:
            List containing two floats
            Lowest and highest value after rescaling.
            Defaults to (0., 1.)
        clip:
            If True, points where data were outside the scaling range
            will be set to the scale min or max appropriately.
            Default is False which continues the scaling beyond min and
            max.

    Returns:
        Output array of scaled data. Has same shape as data.
    """
    data_left = np.min(data) if data_range is None else data_range[0]
    data_right = np.max(data) if data_range is None else data_range[1]
    scale_left = scale_range[0]
    scale_right = scale_range[1]
    # Range check
    if data_left == data_right:
        raise ValueError(
            "Cannot rescale a zero input range ({} -> {})".format(data_left, data_right)
        )

    if scale_left == scale_right:
        raise ValueError(
            "Cannot rescale a zero output range ({} -> {})".format(
                scale_left, scale_right
            )
        )

    result = (
        (data - data_left) * (scale_right - scale_left) / (data_right - data_left)
    ) + scale_left
    if clip:
        result = np.clip(
            result, min(scale_left, scale_right), max(scale_left, scale_right)
        )
    return result


