import copy
import warnings
import numpy as np
import pyproj
from packaging.version import Version


def proj_is_same(p1, p2):
    """Checks is two pyproj projections are equal.

    See https://github.com/jswhit/pyproj/issues/15#issuecomment-208862786

    Parameters
    ----------
    p1 : pyproj.Proj
        first projection
    p2 : pyproj.Proj
        second projection
    """
    if has_gdal:
        # this is more robust, but gdal is a pain
        s1 = osr.SpatialReference()
        s1.ImportFromProj4(p1.srs)
        s2 = osr.SpatialReference()
        s2.ImportFromProj4(p2.srs)
        return s1.IsSame(s2) == 1  # IsSame returns 1 or 0
    else:
        # at least we can try to sort it
        p1 = '+'.join(sorted(p1.srs.split('+')))
        p2 = '+'.join(sorted(p2.srs.split('+')))
        return p1 == p2


def _transform_internal(p1, p2, x, y, **kwargs):
    if hasattr(pyproj, 'Transformer'):
        trf = pyproj.Transformer.from_proj(p1, p2, **kwargs)
        with warnings.catch_warnings():
            # https://github.com/pyproj4/pyproj/issues/1415
            warnings.filterwarnings("ignore", category=DeprecationWarning,
                                    message=".*ndim > 0 to a scalar.*")
            return trf.transform(x, y)
    else:
        return pyproj.transform(p1, p2, x, y, **kwargs)


def transform_proj(p1, p2, x, y, nocopy=False):
    """Wrapper around the pyproj.transform function.

    Transform points between two coordinate systems defined by the Proj
    instances p1 and p2.

    When two projections are equal, this function avoids quite a bunch of
    useless calculations. See https://github.com/jswhit/pyproj/issues/15

    Parameters
    ----------
    p1 : pyproj.Proj
        projection associated to x and y
    p2 : pyproj.Proj
        projection into which x, y must be transformed
    x : ndarray
        eastings
    y : ndarray
        northings
    nocopy : bool
        in case the two projections are equal, you can use nocopy if you wish
    """

    try:
        # This always makes a copy, even if projections are equivalent
        return _transform_internal(p1, p2, x, y, always_xy=True)
    except TypeError:
        if proj_is_same(p1, p2):
            if nocopy:
                return x, y
            else:
                return copy.deepcopy(x), copy.deepcopy(y)

        return _transform_internal(p1, p2, x, y)

