from __future__ import annotations

import xarray as xr
import xugrid as xu

def convert_pointwaterhead_freshwaterhead(
    pointwaterhead: GridDataArray,
    density: GridDataArray,
    elevation: GridDataArray,
    density_fresh: float = 1000.0,
) -> GridDataArray:
    r"""Function to convert point water head (as outputted by seawat)
    into freshwater head, using Eq.3 from Guo, W., & Langevin, C. D. (2002):

    .. math:: h_{f}=\frac{\rho}{\rho_{f}}h-\frac{\rho-\rho_{f}}{\rho_{f}}Z

    An edge case arises when the head is below the cell centre, or entirely below
    the cell. Strictly applying Eq.3 would result in freshwater heads that are
    lower than the original point water head, which is physically impossible. This
    function then outputs the freshwaterhead for the uppermost underlying cell where
    the original point water head exceeds the cell centre.

    Parameters
    ----------
    pointwaterhead : float or xr.DataArray/xu.UgridDataArray of floats
        the point water head as outputted by SEAWAT, in m.
    density : float or xr.DataArray/xu.UgridDataArray of floats
        the water density at the same locations as `pointwaterhead`.
    elevation : float or xr.DataArray/xu.UgridDataArray of floats
        elevation at the same locations as `pointwaterhead`, in m.
    density_fresh : float, optional
        the density of freshwater (1000 kg/m3), or a different value if
        different units are used, or a different density reference is required.

    Returns
    -------
    freshwaterhead : float or xr.DataArray/xu.UgridDataArray of floats
    """

    freshwaterhead = (
        density / density_fresh * pointwaterhead
        - (density - density_fresh) / density_fresh * elevation
    )

    # edge case: point water head below z
    # return freshwater head of top underlying cell where elevation < pointwaterhead
    # only for grids with layers
    if (
        isinstance(pointwaterhead, (xr.DataArray, xu.UgridDataArray))
        and "layer" in pointwaterhead.dims
    ):
        freshwaterhead = freshwaterhead.where(pointwaterhead > elevation)
        freshwaterhead = freshwaterhead.bfill(dim="layer")

    return freshwaterhead
