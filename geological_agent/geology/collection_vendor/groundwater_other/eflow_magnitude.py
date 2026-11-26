import numpy as np

def ma1(flows, datetimes, hydro_years, drainage_area):
    """Mean daily flow for the entire daily flow record.

    :Calculation Details:
        Calculate the mean for the whole daily flow record.

    """
    # calculations for entire time series
    sfc = np.mean(flows, axis=0)

    return sfc


def ma2(flows, datetimes, hydro_years, drainage_area):
    """Median daily flow for the entire daily flow record.

    :Calculation Details:
        Calculate the median for the whole daily flow record.

    """
    # calculations for entire time series
    sfc = np.median(flows, axis=0)

    return sfc


def ma3(flows, datetimes, hydro_years, drainage_area):
    """Mean annual coefficient of variation for daily flows.

    :Calculation Details:
        Calculate the standard deviation and the mean of the daily flows
        for each hydrological year. Divide the values of the former by
        the values of the latter to get the coefficients of variation
        for each hydrological year. Calculate the mean of these
        coefficients.

    """
    # calculations per hydrological year
    info = np.zeros((hydro_years.shape[0], flows.shape[1]), dtype=np.float64)
    for hy, mask in enumerate(hydro_years):
        info[hy, :] = (np.std(flows[mask, :], ddof=1, axis=0)
                       / np.mean(flows[mask, :], axis=0))
    # calculations for entire time series
    sfc = np.mean(info, axis=0) * 100

    return sfc


def ma4(flows, datetimes, hydro_years, drainage_area):
    """Variability in the percentiles on log10 for the entire daily
    flow record.

    :Calculation Details:
        Compute the decimal logarithm of the daily flow values.
        Calculate the 5th, 10th, 15th, ..., 95th percentiles of these
        log-transformed values. Calculate the standard deviation and the
        mean of the 19 percentile values. Multiply the former by 100 and
        divide the result by the latter.

    """
    log_f = np.copy(flows)
    # replace log10(0) by log10(0.01) if necessary
    log_f[log_f == 0.0] = 0.01
    log_f = np.log10(log_f, dtype=np.float64)
    # calculations for entire time series
    perc = np.percentile(log_f, (5, 10, 15, 20, 25, 30, 35, 40, 45, 50,
                                 55, 60, 65, 70, 75, 80, 85, 90, 95), axis=0)
    sfc = np.std(perc, ddof=1, axis=0) * 100 / np.mean(perc, axis=0)

    return sfc


def ma5(flows, datetimes, hydro_years, drainage_area):
    """Skewness of the daily flow values.

    :Calculation Details:
        Calculate the mean flow for the whole daily flow record. Divide
        by the median flow for the whole daily flow record.

    """
    # calculations for entire time series
    sfc = np.mean(flows, axis=0) / np.median(flows, axis=0)

    return sfc


def ma6(flows, datetimes, hydro_years, drainage_area):
    """Ratio between 90th and 10th percentiles for the entire record.

    :Calculation Details:
        Calculate the 90th percentile and the 10th percentile of the
        daily flow record. Divide the former value by the latter value.

    """
    # calculations for entire time series
    sfc = np.percentile(flows, 90, axis=0) / np.percentile(flows, 10, axis=0)

    return sfc


def ma7(flows, datetimes, hydro_years, drainage_area):
    """Ratio between 80th and 20th percentiles for the entire record.

    :Calculation Details:
        Calculate the 80th percentile and the 20th percentile of the
        daily flow record. Divide the former value by the latter value.

    """
    # calculations for entire time series
    sfc = np.percentile(flows, 80, axis=0) / np.percentile(flows, 20, axis=0)

    return sfc
