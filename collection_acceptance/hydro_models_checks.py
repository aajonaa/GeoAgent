from .hydro_models_checks_baseline import *
from .hydro_models_checks_baseline import check as baseline_check
def check(name,data,args,out=None):
    if name=="EarthCatchmodLinearStoreStep":
        from .hydro_cpu_catchmod import check as catch_check
        return catch_check(name,data,args)
    return baseline_check(name,data,args,out)
