import numpy as np

def mean_std(src, ref, **kwargs):
    """
    scales the input datasets so that they have the same mean
    and standard deviation afterwards

    Parameters
    ----------
    src : numpy.array
        input dataset which will be scaled
    ref : numpy.array
        src will be scaled to this dataset

    Returns
    -------
    scaled dataset : numpy.array
        dataset src with same mean and standard deviation as ref
    """
    return ((src - np.mean(src)) / np.std(src)) * np.std(ref) + np.mean(ref)
