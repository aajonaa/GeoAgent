"""Unmodified numerical oracles from the 58-test independent acceptance."""
import math

def check_spectral(result,args,gain=0.8,phase=-math.pi/6):
    import numpy as np
    f=np.asarray(result['frequency_Hz'])
    expected=1/(32*3600.)
    index=int(np.argmin(np.abs(f-expected)))
    assert math.isclose(f[index],expected,rel_tol=1e-14,abs_tol=1e-18)
    assert result['valid_response'][index]
    assert math.isclose(result['gain_head_per_pressure_head'][index],gain,rel_tol=1e-10,abs_tol=1e-11)
    error=np.angle(np.exp(1j*(result['phase_rad'][index]-phase)))
    assert abs(error)<1e-10
    assert math.isclose(result['coherence'][index],1.,abs_tol=1e-12)
    dt=args['times_seconds'][1]-args['times_seconds'][0]
    length=result['samples_per_segment']
    assert math.isclose(result['pressure_head_psd_m2_per_Hz'][index],length*dt/3,rel_tol=1e-10)
    df=f[1]-f[0]
    assert math.isclose(math.fsum(result['pressure_head_psd_m2_per_Hz'])*df,0.5,rel_tol=1e-10)
    assert len(f)==length//2+1
    for key in ['gain_head_per_pressure_head','phase_rad','coherence','pressure_head_psd_m2_per_Hz','groundwater_head_psd_m2_per_Hz','valid_response']:
        assert len(result[key])==len(f)
    assert not result['valid_response'][0]
    for key in ['gain_head_per_pressure_head','phase_rad','coherence']:
        assert all((value is not None)==valid for value,valid in zip(result[key],result['valid_response']))
    assert result['units']=={'frequency_Hz':'Hz','gain_head_per_pressure_head':'1','phase_rad':'rad','coherence':'1',
        'pressure_head_psd_m2_per_Hz':'m2/Hz','groundwater_head_psd_m2_per_Hz':'m2/Hz','sample_interval_seconds':'s'}

def check_forecast(result,args):
    import numpy as np
    from scipy.stats import t
    def design(phases,predictors):
        angle=2*np.pi*np.asarray(phases)
        return np.column_stack((np.ones(len(phases)),np.sin(angle),np.cos(angle),np.asarray(predictors)))
    x=design(args['training_annual_phase'],args['training_predictors_dimensionless'])
    xf=design(args['forecast_annual_phase'],args['forecast_predictors_dimensionless'])
    y=np.asarray(args['observed_flow_m3_s'])
    coefficients=np.linalg.lstsq(x,y,rcond=None)[0]
    mean=xf@coefficients
    residual=y-x@coefficients
    degrees=len(y)-x.shape[1]
    variance=float(residual@residual/degrees)
    mean_var=variance*np.einsum('ij,jk,ik->i',xf,np.linalg.inv(x.T@x),xf)
    quantile=float(t.ppf((1+args.get('confidence_level',.95))/2,degrees))
    expected={'forecast_mean_m3_s':mean,'mean_ci_lower_m3_s':mean-quantile*np.sqrt(mean_var),
        'mean_ci_upper_m3_s':mean+quantile*np.sqrt(mean_var),
        'prediction_lower_m3_s':mean-quantile*np.sqrt(mean_var+variance),
        'prediction_upper_m3_s':mean+quantile*np.sqrt(mean_var+variance)}
    for name,values in expected.items():
        np.testing.assert_allclose(result[name],values,rtol=1e-10,atol=1e-10)
        assert result['units'][name]=='m3/s'
    np.testing.assert_allclose(result['coefficients_m3_s'],coefficients,rtol=1e-10,atol=1e-10)
    assert result['units']['coefficients_m3_s']=='m3/s'
    assert result['residual_df']==degrees and result['design_rank']==x.shape[1]
    assert result['forecast_samples']==len(xf) and result['training_samples']==len(x)
    assert result['contains_negative_statistical_output']==bool(any(np.any(values<0) for values in expected.values()))

def check(name, result, args, output_dir=None):
    if name == "ScipyGroundwaterFrequencyResponse":
        check_spectral(result, args)
    elif name == "StatsmodelsSeasonalFlowForecast":
        check_forecast(result, args)
    else:
        raise ValueError("Unknown approved functional replacement: " + name)
    assert output_dir is None
    assert result["artifacts"] == []
    assert result["provenance"]["output_sha256"] == {}
