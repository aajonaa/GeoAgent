"""Reviewed closed CPU profile calls; no scientific dependency is imported here."""
from functools import wraps
from pathlib import Path
from ..native_cpu_bridge import invoke

def transport(function):
    @wraps(function)
    def call(value=None,*,args=None,output_dir=None):
        return function(value,args=args,output_dir=output_dir)
    return call

def fixed(name,value,args,output_dir):
    return invoke(name,value,args=args,output_dir=output_dir,implementation_path=Path(__file__))

@transport
def pyflo_curve_number_runoff(value=None,*,args=None,output_dir=None):
    return fixed('HydroModelsPyFloCurveNumberRunoff',value,args,output_dir)

@transport
def pysteps_precipitation_advection(value=None,*,args=None,output_dir=None):
    return fixed('HydroModelsPySTEPSPrecipitationAdvection',value,args,output_dir)

@transport
def catchmod_linear_store_step(value=None,*,args=None,output_dir=None):
    return fixed('EarthCatchmodLinearStoreStep',value,args,output_dir)

@transport
def superflex_unit_hydrograph(value=None,*,args=None,output_dir=None):
    return fixed('HydroModelsSuperflexUnitHydrograph',value,args,output_dir)

@transport
def hydpy_flow_scores(value=None,*,args=None,output_dir=None):
    return fixed('HydroModelsHydPyFlowScores',value,args,output_dir)

@transport
def pydem_terrain_derivatives(value=None,*,args=None,output_dir=None):
    return fixed('HydroModelsPyDEMTerrainDerivatives',value,args,output_dir)
