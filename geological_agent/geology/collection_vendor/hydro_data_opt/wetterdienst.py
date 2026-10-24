# Integration scaffold around unchanged upstream source excerpts.
from __future__ import annotations
def reduce_to_elevation(
    values: pl.Series,
    lapse_rate: float | None,
    station_elevation: float | None,
    target_elevation: float | None,
) -> pl.Series | None:
    """Bring a station's readings to the elevation they are being asked about.

    A quantity that falls with height -- air temperature at about 0.65 K per 100 m, a dew point at
    0.2 -- says something different at a valley station than at a summit one, and interpolating the
    two as they come fits that vertical difference as though it were horizontal. Around Garmisch
    the stations within 40 km span 630 m to 2956 m, which is 15 K of air temperature; even the flat
    country around Frankfurt spans 495 m, or 3.2 K.

    The correction needs an elevation for the target, which the interpolation cannot supply itself: an
    elevation taken from the same linear interpolation cancels out of it exactly, leaving the result
    unchanged. So it is applied only when a caller says where the point is, and otherwise the
    readings are left as they came.

    A station whose own elevation is unknown cannot be placed against that target at all, and
    thirteen providers have such stations -- every one of FMI's, IPMA's and the Environment
    Agency's, and a scattering of ECCC's and met.no's. Letting its readings through uncorrected
    would put them at their own altitude while their neighbours are moved to the caller's, which
    is a worse answer than leaving the station out: hence `None`, meaning it has nothing to
    contribute to a question about this elevation.

    Args:
        values: the station's readings
        lapse_rate: the rate the quantity falls at, in the values' own unit per metre
        station_elevation: the elevation the station stands at, in metres
        target_elevation: the elevation asked about, in metres

    Returns:
        The readings as they would read at the target elevation, or None where the station cannot be
        placed against it

    """
    if target_elevation is None or not lapse_rate:
        return values
    if station_elevation is None:
        return None
    return values - lapse_rate * (target_elevation - station_elevation)


