# Adaptation: isolated upstream function bodies with import/class glue added.
# Copyright (C) 2017 The Computational Hydrology Group, University of Washington
# Original algorithms unchanged; full upstream license in licenses/.
import numpy as np
import pandas as pd
from . import metsim_constants as cnst

def calc_pet(rad: np.array, ta: np.array, dayl: np.array,
             pa: float, dt: float=0.2) -> np.array:
    '''
    Calculates the potential evapotranspiration for aridity corrections in
    `calc_vpd()`, according to Kimball et al., 1997

    Parameters
    ----------
    rad:
        daylight average incident shortwave radiation (W/m2)
    ta:
        daylight average air temperature (deg C)
    dayl:
        daylength (s)
    pa:
        air pressure (Pa)
    dt:
        offset for saturation vapor pressure calculation

    Returns
    -------
    pet
        Potential evapotranspiration (cm/day)
    '''
    # Definition of parameters:
    # rnet       # (W m-2) absorbed shortwave radiation avail. for ET
    # lhvap      # (J kg-1) latent heat of vaporization of water
    # gamma      # (Pa K-1) psychrometer parameter
    # dt = 0.2   # offset for saturation vapor pressure calculation
    # t1, t2     # (deg C) air temperatures
    # pvs1, pvs2 # (Pa)   saturated vapor pressures
    # pet        # (kg m-2 day-1) potential evapotranspiration
    # s          # (Pa K-1) slope of saturated vapor pressure curve

    # calculate absorbed radiation, assuming albedo = 0.2  and ground
    # heat flux = 10% of absorbed radiation during daylight
    rnet = rad * 0.72

    # calculate latent heat of vaporization as a function of ta
    lhvap = 2.5023e6 - 2430.54 * ta

    # calculate the psychrometer parameter: gamma = (cp pa)/(lhvap epsilon)
    # where:
    # cp       (J/kg K)   specific heat of air
    # epsilon  (unitless) ratio of molecular weights of water and air
    gamma = cnst.CP * pa / (lhvap * cnst.EPS)

    # estimate the slope of the saturation vapor pressure curve at ta
    # temperature offsets for slope estimate
    t1 = ta + dt
    t2 = ta - dt

    # calculate saturation vapor pressures at t1 and t2, using formula from
    # Abbott, P.F., and R.C. Tabony, 1985. The estimation of humidity
    # parameters. Meteorol. Mag., 114:49-56.
    pvs1 = svp(t1)
    pvs2 = svp(t2)

    # calculate slope of pvs vs. T curve near ta
    s = (pvs1 - pvs2) / (t1 - t2)
    # can this be s = svp_slope(ta)? JJH

    # calculate PET using Priestly-Taylor approximation, with coefficient
    # set at 1.26. Units of result are kg/m^2/day, equivalent to mm water/day
    pet = (1.26 * (s / (s + gamma)) * rnet * dayl) / lhvap

    # return a value in centimeters/day, because this value is used in a ratio
    # to annual total precip, and precip units are centimeters
    return (pet / 10.)


def svp(temp: np.array, a: float=0.61078, b: float=17.269, c: float=237.3):
    '''
    Compute the saturated vapor pressure.

    .. [2] Maidment, David R. Handbook of hydrology. McGraw-Hill Inc.,
      1992 Equation 4.2.2.

    Parameters
    ----------
    temp:
        Temperature (degrees Celsius)
    a:
        (optional) parameter
    b:
        (optional) parameter
    c:
        (optional) parameter

    Returns
    -------
    svp:
        Saturated vapor pressure (Pa)
    '''
    if isinstance(temp, pd.Series):
        raise Exception()
    svp = a * np.exp((b * temp) / (c + temp))
    inds = np.nonzero(temp < 0.)[0]
    svp[inds] *= 1.0 + .00972 * temp[inds] + .000042 * np.power(temp[inds], 2)
    return svp * 1000.


