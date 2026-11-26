/* New fixed ABI glue, 2026-10-22; original archived Kiss FFT is unchanged. */
#include <stddef.h>
#include <math.h>
#include "kiss_fft.h"
#define GEO_EXPORT __attribute__((visibility("default")))

GEO_EXPORT int geo_madagascar_fft(size_t n, const double *samples,
        double *real, double *imag)
{
    if (!samples || !real || !imag || n < 2 || n > 4096) return 1;
    for (size_t i = 0; i < n; ++i)
        if (!isfinite(samples[i]) || fabs(samples[i]) > 1e12) return 1;
    kiss_fft_cfg cfg = kiss_fft_alloc((int)n, 0, NULL, NULL);
    kiss_fft_cpx *in = calloc(n, sizeof(*in));
    kiss_fft_cpx *out = calloc(n, sizeof(*out));
    if (!cfg || !in || !out) {
        free(cfg); free(in); free(out); return 2;
    }
    for (size_t i = 0; i < n; ++i) in[i].r = (kiss_fft_scalar)samples[i];
    kiss_fft(cfg, in, out);
    int code = 0;
    for (size_t i = 0; i < n; ++i) {
        real[i] = out[i].r; imag[i] = out[i].i;
        if (!isfinite(real[i]) || !isfinite(imag[i])) code = 3;
    }
    free(out); free(in); free(cfg);
    return code;
}

