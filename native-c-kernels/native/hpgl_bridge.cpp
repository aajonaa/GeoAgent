/* New fixed ABI glue, 2026-10-22. Pair selection and semivariance are
 * calculated exclusively by unchanged HPGL variograms.cpp. */
#include <cmath>
#include <cstddef>
#include <vector>
#include <new>
#include "api.h"
#define GEO_EXPORT __attribute__((visibility("default")))

extern "C" GEO_EXPORT int geo_hpgl_variogram(size_t n, const double *xs,
        const double *ys, const double *zs, const double *values,
        int axis, double separation, double width, double first,
        int lags, double bandwidth, double *gamma)
{
    if (!xs || !ys || !zs || !values || !gamma || n < 2 || n > 512 ||
        axis < 0 || axis > 2 || lags < 1 || lags > 64 ||
        !std::isfinite(separation) || separation < 1e-6 || separation > 1e7 ||
        !std::isfinite(width) || width < 1e-6 || width > separation ||
        !std::isfinite(first) || first <= width/2 || first > 1e7 ||
        !std::isfinite(bandwidth) || bandwidth < 1e-6 || bandwidth > 1e7)
        return 1;
    for (size_t i = 0; i < n; ++i)
        if (!std::isfinite(xs[i]) || std::fabs(xs[i]) > 1e7 ||
            !std::isfinite(ys[i]) || std::fabs(ys[i]) > 1e7 ||
            !std::isfinite(zs[i]) || std::fabs(zs[i]) > 1e7 ||
            !std::isfinite(values[i]) || std::fabs(values[i]) > 1e12) return 1;
    try {
        std::vector<float> x(n), y(n), z(n), v(n), output(lags);
        for (size_t i = 0; i < n; ++i) {
            x[i] = xs[i]; y[i] = ys[i]; z[i] = zs[i]; v[i] = values[i];
        }
        variogram_search_template_t search = {};
        search.m_num_lags = lags; search.m_lag_separation = separation;
        search.m_lag_width = width; search.m_first_lag_distance = first;
        search.m_tol_distance = 0;
        search.m_ellipsoid.m_R1 = bandwidth;
        search.m_ellipsoid.m_R2 = bandwidth;
        search.m_ellipsoid.m_R3 = bandwidth;
        search.m_ellipsoid.m_direction1.m_data[axis] = 1;
        search.m_ellipsoid.m_direction2.m_data[(axis+1)%3] = 1;
        search.m_ellipsoid.m_direction3.m_data[(axis+2)%3] = 1;
        cont_point_set_t points = {x.data(), y.data(), z.data(), v.data(), (int)n};
        calc_variograms_from_point_set(&search, &points, output.data(), lags);
        for (int i = 0; i < lags; ++i) {
            gamma[i] = output[i];
            if (!std::isfinite(gamma[i])) return 3;
        }
    } catch (const std::bad_alloc &) { return 2; }
    return 0;
}

