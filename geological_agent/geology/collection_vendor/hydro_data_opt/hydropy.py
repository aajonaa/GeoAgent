# Integration scaffold around unchanged upstream source excerpts.
import pandas as pd
import numpy as np
def get_baseflow_chapman(flowserie, recession_time):
    """

    Parameters
    ----------
    flowserie :  pd.TimeSeries
        River discharge flowserie
    recession_time : float [0-1]
        recession constant

    Notes
    ------
    $$Q_b(i) = \frac{k}{2-k}Q_b(i-1) + \frac{1-k}{2-k}Q(i)$$

    """

    secterm = (1.-recession_time)*flowserie/(2.-recession_time)

    baseflow = np.empty(flowserie.shape[0])
    for i, timestep in enumerate(baseflow):
        if i == 0:
            baseflow[i] = 0.0
        else:
            baseflow[i] = recession_time*baseflow[i-1]/(2.-recession_time) + \
                            secterm.values[i]
    baseflow = pd.DataFrame(baseflow, index=flowserie.index)
    return baseflow


