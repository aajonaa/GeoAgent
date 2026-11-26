"""Original VIC, Madagascar and HPGL kernels through a fixed CPU profile."""
from pathlib import Path

from .native_cpu_bridge import invoke


from functools import wraps as _wraps


def _native_entrypoint(function):
    @_wraps(function)
    def call(value=None, *, args=None, output_dir=None):
        return function(value, args=args, output_dir=output_dir)
    return call


@_native_entrypoint
def HydroVICPrecipitationPhase(value=None, *, args=None, output_dir=None):
    return invoke('HydroVICPrecipitationPhase', value, args=args, output_dir=output_dir, implementation_path=Path(__file__))


@_native_entrypoint
def SeismicMadagascarFFT(value=None, *, args=None, output_dir=None):
    return invoke('SeismicMadagascarFFT', value, args=args, output_dir=output_dir, implementation_path=Path(__file__))


@_native_entrypoint
def GeoHPGLDirectionalSemivariogram(value=None, *, args=None, output_dir=None):
    return invoke('GeoHPGLDirectionalSemivariogram', value, args=args, output_dir=output_dir, implementation_path=Path(__file__))
