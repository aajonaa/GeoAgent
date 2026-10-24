/* New ABI glue, 2026-10-22. Scientific partition remains upstream VIC C. */
#include <stddef.h>
#include <stdlib.h>
#include <math.h>
#define GEO_EXPORT __attribute__((visibility("default")))
extern double calc_rainonly(double, double, double, double);

/* Upstream only reaches this fatal path for invalid thresholds. The ABI
 * rejects those before calling upstream; no log or model state is needed. */
void log_err(const char *format, ...) { (void)format; abort(); }

GEO_EXPORT int geo_vic_partition(size_t n, const double *temp,
        const double *prec, double max_snow, double min_rain,
        double *rain, double *snow)
{
    if (!temp || !prec || !rain || !snow || n < 1 || n > 4096 ||
        !isfinite(max_snow) || !isfinite(min_rain) ||
        max_snow > 100 || min_rain < -100 || max_snow <= min_rain)
        return 1;
    for (size_t i = 0; i < n; ++i)
        if (!isfinite(temp[i]) || fabs(temp[i]) > 100 ||
            !isfinite(prec[i]) || prec[i] < 0 || prec[i] > 100000)
            return 1;
    for (size_t i = 0; i < n; ++i) {
        rain[i] = calc_rainonly(temp[i], prec[i], max_snow, min_rain);
        snow[i] = prec[i] - rain[i]; /* Complement, not a substitute model. */
        if (!isfinite(rain[i]) || !isfinite(snow[i])) return 3;
    }
    return 0;
}

