# Integration scaffold around unchanged upstream source excerpts.
import numpy as np
import logging
def nashsutcliffe(evaluation, simulation):
    """
    Nash-Sutcliffe model efficinecy

        .. math::

         NSE = 1-\\frac{\\sum_{i=1}^{N}(e_{i}-s_{i})^2}{\\sum_{i=1}^{N}(e_{i}-\\bar{e})^2}

    :evaluation: Observed data to compared with simulation data.
    :type: list

    :simulation: simulation data to compared with evaluation data
    :type: list

    :return: Nash-Sutcliff model efficiency
    :rtype: float

    """
    if len(evaluation) == len(simulation):
        s, e = np.array(simulation), np.array(evaluation)
        # s,e=simulation,evaluation
        mean_observed = np.nanmean(e)
        # compute numerator and denominator
        numerator = np.nansum((e - s) ** 2)
        denominator = np.nansum((e - mean_observed) ** 2)
        # compute coefficient
        return 1 - (numerator / denominator)

    else:
        logging.warning(
            "evaluation and simulation lists does not have the same length."
        )
        return np.nan


