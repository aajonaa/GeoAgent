import numpy as np

def get_water_table(heads, hdry=-1e30, hnoflo=1e30, masked_values=None):
    """
    Get a 2D array representing the water table elevation for each
    stress period in heads array.

    Parameters
    ----------
    heads : 3 or 4-D np.ndarray
        Heads array.
    hdry : real
        The head that is assigned to cells that are converted to dry
        during a simulation. By default, -1e30.
    hnoflo : real
        The value of head assigned to all inactive (no flow) cells
        throughout the simulation, including vertical pass-through cells in
        MODFLOW 6. By default, 1e30.
    masked_values : list
        List of any values (in addition to hdry and hnoflo) that should
        be masked in the water table calculation.

    Returns
    -------
    wt : 2 or 3-D np.ndarray of water table elevations
        for each stress period.

    """
    heads = np.array(heads, ndmin=4)
    mask = (heads == hdry) | (heads == hnoflo)
    if masked_values is not None:
        for val in masked_values:
            mask = mask | (heads == val)
    k = (~mask).argmax(axis=1)
    per, i, j = np.indices(k.shape)
    wt = heads[per.ravel(), k.ravel(), i.ravel(), j.ravel()].reshape(k.shape)
    wt = np.squeeze(wt)
    mask = (wt == hdry) | (wt == hnoflo)
    if masked_values is not None:
        for val in masked_values:
            mask = mask | (wt == val)
    wt = np.ma.masked_array(wt, mask)
    return wt
