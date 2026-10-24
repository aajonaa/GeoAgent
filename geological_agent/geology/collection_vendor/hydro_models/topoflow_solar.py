# Copyright (c) 2005-2013 Scott D. Peckham. See licenses/topoflow_old_LICENSE.txt.
# Exact source excerpts, with NumPy import supplied for this bounded module.
import numpy as np

def Solar_Constant():

    return np.float64(1367)   # [Watts / m^2]
    
#   Solar_Constant()
#------------------------------------------------------------------------
def Day_Angle( Julian_day, DEGREES=False ):

    #---------------------------------------------------------
    # Notes:  The Julian day does not need to be an integer;
    #         decimal values can be used for more precision.
    #---------------------------------------------------------
    angle = (2 * np.pi) * (Julian_day - np.float64(1)) / np.float64(365)
    
    if (DEGREES):    
        angle = angle * (np.float64(180) / np.pi)
    
    return angle
    
#   Day_Angle()
#------------------------------------------------------------------------
def Eccentricity_Correction( day_angle ):

    E0 = np.float64(1.000110) + \
         (np.float64(0.034221) * np.cos(day_angle)) + \
         (np.float64(0.001280) * np.sin(day_angle)) + \
         (np.float64(0.000719) * np.cos(np.float64(2) * day_angle)) + \
         (np.float64(0.000077) * np.sin(np.float64(2) * day_angle))
    
    return E0   # [unitless, ratio of two lengths]
    
#   Eccentricity_Correction()
#------------------------------------------------------------------------
def Declination( day_angle, DEGREES=False, DMS=False ):

    ################################################################
    # NB! Make sure that DEGREES and DMS should default to False.
    ################################################################
    
    #-----------------------------------------------------------
    # Note:  The declination reaches its lowest value of -23.5
    #        degrees on the Winter Solstice (Dec. 21/22) and
    #        reaches its highest value of 23.5 degrees on the
    #        Summer Solstice (June 21/22).  It is zero for
    #        both the Vernal Equinox (Mar. 20/21) and the
    #        Autumnal Equinox (Sept. 22/23).  The value of
    #        23.4397 degrees is the fixed tilt angle of the
    #        Earth's axis from from the plane of the ecliptic.
    #-----------------------------------------------------------  
    delta = np.float64(0.006918) - \
            (np.float64(0.399912) * np.cos(day_angle)) + \
            (np.float64(0.070257) * np.sin(day_angle)) - \
            (np.float64(0.006758) * np.cos(np.float64(2) * day_angle)) + \
            (np.float64(0.000907) * np.sin(np.float64(2) * day_angle)) - \
            (np.float64(0.002697) * np.cos(np.float64(3) * day_angle)) + \
            (np.float64(0.001480) * np.sin(np.float64(3) * day_angle))
    
    #------------------------------------
    # Convert from radians to degrees ?
    #------------------------------------
    if (DEGREES):    
        delta = delta * (np.float64(180) / np.pi)
    
    #----------------------------------------
    # Convert from radians to "decimal DMS"
    #----------------------------------------
    if (DMS):    
        delta = delta * (np.float64(180) / np.pi)  # [decimal degrees]
        deg = np.int16(delta)
        min = np.int16((delta - deg) * np.float64(60))
        sec = np.int16(((delta - deg) * np.float64(60) - min) * np.float64(60))
        delta = deg + (min / np.float64(100)) + (sec / np.float64(10000))   # [decimal DMS, DD.MMSS]
    
    return delta
    
#   Declination()
#------------------------------------------------------------------------
def Earth_Angular_Velocity():

    #---------------------------------------------------
    # Notes:  Compare to Earth_Rotation_Rate function.
    #---------------------------------------------------
    deg_per_hour = np.float64(360) / np.float64(24)   #(equals 15)
    rad_per_hour = deg_per_hour * (np.pi / np.float64(180))
    
    return rad_per_hour
    
#   Earth_Angular_Velocity()
#------------------------------------------------------------------------
def ET_Radiation_Flux( lat_deg, Julian_day, th ):

    #------------------------------------------------------------
    # Notes:  This is the instantaneous extraterrestrial
    #         radiation flux on a horizontal plane at a time
    #         th hours before (-) or after (+) true solar noon.
    #------------------------------------------------------------
    I_sc = Solar_Constant()             # [W / m^2]
    omega = Earth_Angular_Velocity()    # [radians / hour]
    #---------------------------------
    Gamma = Day_Angle(Julian_day)              # [radians]
    delta = Declination(Gamma)                 # [radians]
    E0 = Eccentricity_Correction(Gamma)        # [unitless]
    lat_rad = lat_deg * (np.pi / np.float64(180))
    #------------------------------------------------------------
    term1 = np.cos(delta) * np.cos(lat_rad) * np.cos(omega * th)
    term2 = np.sin(delta) * np.sin(lat_rad)
    K_ET  = I_sc * E0 * (term1 + term2)
    
    #---------------------------
    # This shouldn't be needed
    #---------------------------
    K_ET = np.maximum( K_ET, 0 )
    
    return K_ET    # [Watts / m^2]
    
#   ET_Radiation_Flux()
#------------------------------------------------------------------------
